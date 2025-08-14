# IoT Energy Monitoring Dashboard

Real-time monitoring and control system for 100+ IoT devices with energy consumption tracking.

## Features
- Real-time device monitoring (1-second updates)
- Remote device control (ON/OFF)
- Energy consumption tracking
- Billing in Bangladeshi Taka (৳8.00/kWh)
- Historical data visualization
- CSV data export with 2MB rotation
- WebSocket real-time communication

## Setup
1. Install Python 3.8+
2. Install requirements: `pip install -r requirements.txt`
3. Configure Tuya devices using TinyTuya wizard
4. Run server: `python tuya_server.py`
5. Open `IoTdashboard.html` in browser

## Demo
- Server runs on `http://localhost:5000`
- Dashboard connects via WebSocket for real-time updates
- Supports 100+ devices with color-coded status indicators

## Technologies
- Backend: Python Flask, TinyTuya, WebSocket
- Frontend: HTML5, CSS3, JavaScript, Chart.js
- Database: SQLite with automated CSV logging