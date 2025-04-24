// --- Helper Functions ---

/**
 * Formats a number for display with appropriate decimal places.
 * @param {number|string|null|undefined} num - The number to format.
 * @param {number} [decimals=8] - Default number of decimals.
 * @returns {string} Formatted number string or 'N/A'.
 */
export function formatNumber(num, decimals = 8) {
    const number = parseFloat(num);
    if (isNaN(number) || num === null || num === undefined) return 'N/A';

    // Adjust decimals based on magnitude
    if (Math.abs(number) >= 1000) decimals = 2;
    else if (Math.abs(number) >= 10) decimals = 4;
    else if (Math.abs(number) >= 0.1) decimals = 6;

    try {
        // Use toLocaleString for better formatting (e.g., thousands separators)
        return number.toLocaleString(undefined, {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals
        });
    } catch (e) {
        console.error("Error formatting number:", num, e);
        // Fallback to toFixed if toLocaleString fails (e.g., in very old environments)
        return number.toFixed(decimals);
    }
}

/**
 * Formats a Unix timestamp (milliseconds) into a locale-specific date/time string.
 * @param {number|string|null|undefined} timestamp - The timestamp in milliseconds.
 * @returns {string} Formatted date/time string or 'N/A' or 'Invalid Date'.
 */
export function formatTimestamp(timestamp) {
    if (!timestamp) return 'N/A';
    try {
        const date = new Date(parseInt(timestamp));
        // Check if the date is valid after parsing
        if (isNaN(date.getTime())) return 'Invalid Date';
        return date.toLocaleString(); // Uses browser's locale settings
    } catch (e) {
        console.error("Error formatting timestamp:", timestamp, e);
        return 'Invalid Date';
    }
}

/**
 * Safely retrieves and optionally parses the value from an input element.
 * Returns null if the input doesn't exist or the value is empty/invalid after parsing.
 * @param {HTMLElement|null} input - The DOM input element.
 * @param {function} [parseFn=(v => v)] - Function to parse the value (e.g., parseFloat, parseInt).
 * @returns {any|null} The parsed value or null.
 */
export function safeValue(input, parseFn = v => v) {
    if (!input) {
        return null;
    }
    // For SELECT elements, just return the value directly
    if (input.tagName === 'SELECT') {
        return input.value;
    }
    // For checkboxes, return the checked state
    if (input.type === 'checkbox') {
        return input.checked;
    }
    // For other inputs, get the value and parse it
    const value = input.value;
    if (value === null || value === undefined || value.trim() === '') {
        return null; // Return null for empty strings
    }
    const parsedValue = parseFn(value);
    // Return null if parsing results in NaN for numeric types
    if (typeof parsedValue === 'number' && isNaN(parsedValue)) {
        return null;
    }
    return parsedValue;
}
