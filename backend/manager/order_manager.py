import logging
from typing import List, Dict, Any
from decimal import Decimal

# Import specific functions and the singleton instance
import binance_client_wrapper as binance_api
from manager.state_manager import state_manager # Import the singleton instance

logger = logging.getLogger(__name__)

class OrderManager:
    def __init__(self):
        """Initializes the OrderManager, loading open orders from the state manager."""
        # Load initial open orders from the singleton state_manager
        # Ensure 'open_orders' exists in state, default to empty list if not
        loaded_orders = state_manager.get_state('open_orders')
        self.open_orders: List[Dict[str, Any]] = loaded_orders if isinstance(loaded_orders, list) else []
        logger.info(f"OrderManager initialized with {len(self.open_orders)} open orders from state.")

    # Correct the type hint for the price parameter to explicitly allow None
    def place_order(self, symbol: str, side: str, order_type: str, quantity: float, price: float | None = None) -> Dict[str, Any] | None:
        """
        Places an order on Binance using the wrapper functions.
        Updates the local open_orders list and the global state on success.
        """
        if order_type.upper() == 'LIMIT' and price is None:
            logger.error("Cannot place LIMIT order without a price.")
            return None

        # Convert float to Decimal for precision before passing to API wrapper
        try:
            # Use context=None for Decimal to avoid global context issues if any
            order_quantity = Decimal(str(quantity))
            order_price = Decimal(str(price)) if price is not None else None
        except Exception as e:
             logger.error(f"Invalid quantity or price format for Decimal conversion: {e}")
             return None

        try:
            # Call the imported function directly
            order_response = binance_api.place_order(
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=order_quantity, # Pass Decimal
                price=order_price      # Pass Decimal or None
            )

            if order_response:
                order_id = order_response.get('orderId')
                if order_id is None:
                     logger.error("Order placed but no orderId returned by API response.")
                     # Still return the response as it might contain useful info
                     return order_response

                # Store order details locally using data from the response where possible
                try:
                    # Use response data preferentially, fall back to input parameters
                    new_order_details = {
                        'order_id': order_id,
                        'symbol': order_response.get('symbol', symbol),
                        'side': order_response.get('side', side),
                        'type': order_response.get('type', order_type),
                        'quantity': float(order_response.get('origQty', quantity)),
                        # Use response price if valid, else use input price (which could be None)
                        'price': float(p) if (p := order_response.get('price')) and p and float(p) > 0 else (price if price is not None else None)
                    }
                except (ValueError, TypeError) as e:
                     logger.error(f"Error processing order response data for local storage: {e}. Using input data.")
                     # Fallback to input data if response parsing fails
                     new_order_details = {
                        'order_id': order_id, 'symbol': symbol, 'side': side,
                        'type': order_type, 'quantity': quantity, 'price': price
                     }

                self.open_orders.append(new_order_details)
                # Use update_state on the singleton instance, ensuring it's a list copy
                state_manager.update_state({'open_orders': list(self.open_orders)})
                logger.info(f"Order placed successfully via API. Order ID: {order_id}. Local state updated.")
                return order_response
            else:
                # The API wrapper function returned None, indicating failure before/during API call
                logger.error("Failed to place order (API wrapper returned None).")
                return None
        except Exception as e:
            # Catch any other unexpected errors during the process
            logger.error(f"Unexpected error during place_order: {e}", exc_info=True)
            return None

    def check_open_orders(self) -> None:
        """
        Checks the status of locally tracked open orders using get_all_orders API call.
        Updates the local open_orders list and the global state.
        Groups checks by symbol to reduce API calls.
        """
        orders_to_remove_ids = set()
        # Create a copy to iterate over, preventing modification issues during loop
        current_open_orders_copy = list(self.open_orders)

        # Group orders by symbol
        orders_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
        for order_details in current_open_orders_copy:
            symbol = order_details.get('symbol')
            order_id = order_details.get('order_id')
            if symbol and order_id: # Ensure basic details are present
                if symbol not in orders_by_symbol:
                    orders_by_symbol[symbol] = []
                orders_by_symbol[symbol].append(order_details)
            else:
                logger.warning(f"Found local order entry with missing symbol/ID: {order_details}. Skipping check.")


        # Check orders for each symbol
        for symbol, symbol_orders in orders_by_symbol.items():
            try:
                # Fetch recent orders for the symbol (adjust limit as needed)
                recent_orders_api = binance_api.get_all_orders(symbol=symbol, limit=50)
                if recent_orders_api is None:
                    logger.warning(f"Could not fetch recent orders for {symbol}. Skipping status check for this symbol.")
                    continue

                # Create a map of recent orders by ID for quick lookup
                recent_orders_map = {o.get('orderId'): o for o in recent_orders_api if o.get('orderId')}

                # Check each locally tracked open order for this symbol
                for local_order in symbol_orders:
                    local_order_id = local_order.get('order_id')
                    if not local_order_id: continue # Should have been filtered, but double check

                    api_order_status_info = recent_orders_map.get(local_order_id)

                    if api_order_status_info:
                        status = api_order_status_info.get('status')
                        # These statuses indicate the order is no longer open
                        if status in ['FILLED', 'CANCELED', 'REJECTED', 'EXPIRED', 'PENDING_CANCEL']:
                            logger.info(f"Order {local_order_id} ({symbol}) status from API: {status}. Marking for removal.")
                            orders_to_remove_ids.add(local_order_id)
                        else:
                            # Status is NEW, PARTIALLY_FILLED, etc. - still considered open
                            logger.debug(f"Order {local_order_id} ({symbol}) status from API: {status}. Keeping.")
                    else:
                        # Not found in recent orders. Could be older, filled long ago, or an issue.
                        # Consider adding logic for staleness check if needed.
                        logger.warning(f"Order {local_order_id} ({symbol}) not found in recent 50 orders from API. Status unknown, keeping for now.")

            except Exception as e:
                logger.error(f"Error checking orders for symbol {symbol}: {e}", exc_info=True)

        # Remove the identified orders from the main list if any were marked
        if orders_to_remove_ids:
            initial_count = len(self.open_orders)
            self.open_orders = [o for o in self.open_orders if o.get('order_id') not in orders_to_remove_ids]
            removed_count = initial_count - len(self.open_orders)

            if removed_count > 0:
                 # Update the global state
                 state_manager.update_state({'open_orders': list(self.open_orders)})
                 logger.info(f"Removed {removed_count} closed/problematic orders based on API status check.")
            else:
                 # This case should ideally not happen if orders_to_remove_ids is populated
                 logger.warning("Orders were marked for removal, but none were removed from the list.")


    def cancel_order(self, symbol: str, order_id: int) -> bool:
        """
        Cancels an open order using the wrapper function.
        Updates local state and global state on successful cancellation confirmation.
        """
        if not isinstance(order_id, int):
             logger.error(f"Invalid order_id type for cancellation: {type(order_id)}. Must be int.")
             return False
        try:
            # Call the imported function directly
            result = binance_api.cancel_order(symbol, order_id)

            # Check result status - 'cancel_order' wrapper returns dict or None
            # Successful if API didn't error AND status indicates cancellation or already done.
            if result and result.get('status') in ['CANCELED', 'UNKNOWN_OR_ALREADY_COMPLETED']:
                logger.info(f"Cancel request for order {order_id} ({symbol}) successful via API (Status: {result.get('status')}).")
                # Remove from local state if present
                initial_count = len(self.open_orders)
                self.open_orders = [order for order in self.open_orders if order.get('order_id') != order_id]
                # Check if removal actually happened
                if len(self.open_orders) < initial_count:
                    state_manager.update_state({'open_orders': list(self.open_orders)}) # Update global state
                    logger.info(f"Order {order_id} removed from local OrderManager state.")
                else:
                    # Order was cancelled but wasn't in our local list (maybe already removed by check_open_orders)
                    logger.warning(f"Order {order_id} was successfully cancelled/already done, but not found in local OrderManager state.")
                return True # Indicate successful cancellation action
            elif result:
                 # API call succeeded but order wasn't cancelled (e.g., wrong state like FILLED)
                 logger.error(f"Failed to cancel order {order_id}. API returned status: {result.get('status')}")
                 return False
            else:
                # result is None, indicating API error occurred within the wrapper function itself
                logger.error(f"Failed to cancel order {order_id} (API call failed in wrapper function).")
                return False
        except Exception as e:
            logger.error(f"Unexpected exception during cancel_order for {order_id}: {e}", exc_info=True)
            return False

    def get_open_orders(self) -> List[Dict[str, Any]]:
        """Returns a copy of the current list of open orders managed by this instance."""
        # Return a copy to prevent external modification of the internal list
        return list(self.open_orders)

# --- Singleton Instance ---
# Create a single instance of OrderManager to be used throughout the application
order_manager = OrderManager()
