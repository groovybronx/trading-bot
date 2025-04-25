let metricsChart = null;
let latencyChart = null;

function initializeMonitoring() {
    // Initialiser les graphiques
    setupMetricsCharts();
    
    // Démarrer la mise à jour périodique
    setInterval(updateMetrics, 5000);
}

function setupMetricsCharts() {
    // Graphique de performance
    const perfCtx = document.getElementById('performanceChart').getContext('2d');
    metricsChart = new Chart(perfCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Profit',
                data: [],
                borderColor: 'rgb(75, 192, 192)',
                tension: 0.1
            }]
        }
    });

    // Graphique de latence
    const latencyCtx = document.getElementById('latencyChart').getContext('2d');
    latencyChart = new Chart(latencyCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Latence (ms)',
                data: [],
                borderColor: 'rgb(255, 99, 132)',
                tension: 0.1
            }]
        }
    });
}

async function updateMetrics() {
    try {
        const response = await fetch('/api/metrics');
        const metrics = await response.json();
        
        // Mettre à jour les indicateurs
        updatePerformanceIndicators(metrics.performance);
        updateSystemIndicators(metrics.system);
        updateRealtimeIndicators(metrics.realtime);
        
        // Mettre à jour les graphiques
        updateCharts(metrics);
        
    } catch (error) {
        console.error('Erreur lors de la mise à jour des métriques:', error);
    }
}

function updatePerformanceIndicators(performance) {
    document.getElementById('winRate').textContent = `${(performance.win_rate * 100).toFixed(2)}%`;
    document.getElementById('profitFactor').textContent = performance.profit_factor.toFixed(2);
    document.getElementById('totalTrades').textContent = performance.total_trades;
    document.getElementById('totalProfit').textContent = performance.total_profit;
}

function updateSystemIndicators(system) {
    document.getElementById('cpuUsage').textContent = `${system.cpu_usage.toFixed(1)}%`;
    document.getElementById('memoryUsage').textContent = `${system.memory_usage.toFixed(1)}%`;
    document.getElementById('networkLatency').textContent = `${system.network_latency.toFixed(0)}ms`;
}

function updateRealtimeIndicators(realtime) {
    document.getElementById('ordersPerMinute').textContent = realtime.orders_per_minute.toFixed(1);
    document.getElementById('wsReconnects').textContent = realtime.websocket_reconnects;
    document.getElementById('avgOrderLatency').textContent = `${realtime.average_order_latency.toFixed(0)}ms`;
}

function updateCharts(metrics) {
    // Mise à jour du graphique de performance
    const timestamp = new Date(metrics.timestamp * 1000).toLocaleTimeString();
    
    // Mettre à jour le graphique de performance
    if (metricsChart.data.labels.length > 50) {
        metricsChart.data.labels.shift();
        metricsChart.data.datasets[0].data.shift();
    }
    metricsChart.data.labels.push(timestamp);
    metricsChart.data.datasets[0].data.push(metrics.performance.total_profit);
    metricsChart.update();
    
    // Mettre à jour le graphique de latence
    if (latencyChart.data.labels.length > 50) {
        latencyChart.data.labels.shift();
        latencyChart.data.datasets[0].data.shift();
    }
    latencyChart.data.labels.push(timestamp);
    latencyChart.data.datasets[0].data.push(metrics.realtime.network_latency);
    latencyChart.update();
}

// Exporter les fonctions
export { initializeMonitoring };
