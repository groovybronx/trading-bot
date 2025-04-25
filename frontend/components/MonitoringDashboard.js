import Chart from 'chart.js/auto';

class MonitoringDashboard {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.charts = {};
        this.initializeDashboard();
    }

    initializeDashboard() {
        this.createDashboardLayout();
        this.initializeCharts();
        this.startMetricsUpdate();
    }

    createDashboardLayout() {
        this.container.innerHTML = `
            <div class="monitoring-grid">
                <div class="monitoring-card">
                    <h3>Performance Metrics</h3>
                    <canvas id="performanceChart"></canvas>
                    <div id="performanceStats"></div>
                </div>
                <div class="monitoring-card">
                    <h3>System Metrics</h3>
                    <canvas id="systemChart"></canvas>
                    <div id="systemStats"></div>
                </div>
                <div class="monitoring-card">
                    <h3>Trading Metrics</h3>
                    <canvas id="tradingChart"></canvas>
                    <div id="tradingStats"></div>
                </div>
                <div class="monitoring-card">
                    <h3>Network Metrics</h3>
                    <canvas id="networkChart"></canvas>
                    <div id="networkStats"></div>
                </div>
            </div>
        `;
    }

    initializeCharts() {
        // Initialiser les graphiques avec Chart.js
        this.charts.performance = new Chart(
            document.getElementById('performanceChart'),
            this.getPerformanceChartConfig()
        );

        this.charts.system = new Chart(
            document.getElementById('systemChart'),
            this.getSystemChartConfig()
        );

        this.charts.trading = new Chart(
            document.getElementById('tradingChart'),
            this.getTradingChartConfig()
        );

        this.charts.network = new Chart(
            document.getElementById('networkChart'),
            this.getNetworkChartConfig()
        );
    }

    async startMetricsUpdate() {
        setInterval(async () => {
            try {
                const metrics = await this.fetchMetrics();
                this.updateDashboard(metrics);
            } catch (error) {
                console.error('Error updating metrics:', error);
            }
        }, 5000);
    }

    async fetchMetrics() {
        const response = await fetch('/api/metrics');
        return await response.json();
    }

    updateDashboard(metrics) {
        this.updatePerformanceMetrics(metrics.performance);
        this.updateSystemMetrics(metrics.system);
        this.updateTradingMetrics(metrics.realtime);
        this.updateCharts(metrics);
    }

    // Configuration des graphiques et méthodes de mise à jour...
}

export default MonitoringDashboard;
