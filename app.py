#!/usr/bin/env python3
"""
CSE407 IoT Energy Monitoring Dashboard
By Md Maruf Hasan | ID: 2021-3-60-101 | Enhanced Tuya Smart Plug Energy Monitor
Dynamic IoT Dashboard for Real-time Device Monitoring and Control
"""

import tinytuya
import time
import json
import csv
import os
import threading
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request, send_from_directory, Response
from flask_socketio import SocketIO, emit
import random
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = 'iot_dashboard_secret_key'
socketio = SocketIO(app, cors_allowed_origins="*")

# Configuration
REAL_DEVICE_CONFIG = {
    'dev_id': 'bf0d5b3c1720e925e0f14a',
    'address': '192.168.68.102',
    'local_key': 'bJI[9`BW:2ErM|]:',
    'version': 3.5
}

# Global variables
devices_data = {}
historical_data = []
real_device = None
device_start_time = datetime.now()
settings = {
    'electricity_rate': 8.0,  # BDT per kWh
    'update_interval': 1,     # seconds
    'file_size_limit': 2      # MB
}

# Database setup
def init_database():
    """Initialize SQLite database for persistent storage"""
    conn = sqlite3.connect('iot_dashboard.db')
    cursor = conn.cursor()
    
    # Create devices table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS devices (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            location TEXT NOT NULL,
            ip_address TEXT,
            device_id TEXT,
            local_key TEXT,
            is_real BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create settings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create historical_data table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS historical_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            voltage REAL,
            current REAL,
            power REAL,
            energy REAL,
            cost REAL,
            FOREIGN KEY (device_id) REFERENCES devices (id)
        )
    ''')
    
    conn.commit()
    conn.close()

def load_devices_from_db():
    """Load devices from database"""
    conn = sqlite3.connect('iot_dashboard.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM devices')
    rows = cursor.fetchall()
    conn.close()
    
    for row in rows:
        device_id, name, device_type, location, ip_address, tuya_device_id, local_key, is_real, created_at = row
        devices_data[device_id] = {
            'id': device_id,
            'name': name,
            'type': device_type,
            'location': location,
            'ip_address': ip_address,
            'tuya_device_id': tuya_device_id,
            'local_key': local_key,
            'status': 'offline',
            'state': False,
            'voltage': 0.0,
            'current': 0.0,
            'power': 0.0,
            'energy': 0.0,
            'temperature': 25.0,
            'humidity': 60.0,
            'last_updated': datetime.now(),
            'is_real': bool(is_real),
            'cost_today': 0.0,
            'uptime': 0
        }

def load_settings_from_db():
    """Load settings from database"""
    global settings
    conn = sqlite3.connect('iot_dashboard.db')
    cursor = conn.cursor()
    cursor.execute('SELECT key, value FROM settings')
    rows = cursor.fetchall()
    conn.close()
    
    for key, value in rows:
        if key in settings:
            try:
                if key == 'electricity_rate':
                    settings[key] = float(value)
                else:
                    settings[key] = int(value)
            except ValueError:
                print(f"Invalid value for setting {key}: {value}")

def save_device_to_db(device_data):
    """Save device to database"""
    conn = sqlite3.connect('iot_dashboard.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO devices 
        (id, name, type, location, ip_address, device_id, local_key, is_real)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        device_data['id'], device_data['name'], device_data['type'],
        device_data['location'], device_data.get('ip_address'),
        device_data.get('tuya_device_id'), device_data.get('local_key'),
        device_data.get('is_real', False)
    ))
    conn.commit()
    conn.close()

def delete_device_from_db(device_id):
    """Delete device from database"""
    conn = sqlite3.connect('iot_dashboard.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM devices WHERE id = ?', (device_id,))
    cursor.execute('DELETE FROM historical_data WHERE device_id = ?', (device_id,))
    conn.commit()
    conn.close()

def save_settings_to_db():
    """Save settings to database"""
    conn = sqlite3.connect('iot_dashboard.db')
    cursor = conn.cursor()
    for key, value in settings.items():
        cursor.execute('''
            INSERT OR REPLACE INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', (key, str(value)))
    conn.commit()
    conn.close()

def serialize_device_data(devices):
    """Convert datetime objects to strings for JSON serialization"""
    serializable_devices = {}
    for device_id, device in devices.items():
        serializable_device = device.copy()
        if isinstance(serializable_device.get('last_updated'), datetime):
            serializable_device['last_updated'] = serializable_device['last_updated'].isoformat()
        serializable_devices[device_id] = serializable_device
    return serializable_devices

def get_next_device_id():
    """Get next available device ID"""
    existing_ids = list(devices_data.keys())
    if not existing_ids:
        return "device_001"
    
    # Extract numbers from existing IDs
    numbers = []
    for device_id in existing_ids:
        try:
            num = int(device_id.split('_')[1])
            numbers.append(num)
        except (IndexError, ValueError):
            continue
    
    if not numbers:
        return "device_001"
    
    next_num = max(numbers) + 1
    return f"device_{next_num:03d}"

def initialize_devices():
    """Initialize devices - load from DB or create default 100 devices"""
    global devices_data
    
    # Load existing devices from database
    load_devices_from_db()
    
    # If no devices in database, create default 100 devices
    if not devices_data:
        print("No devices found in database. Creating default 100 devices...")
        
        for i in range(1, 101):
            device_id = f"device_{i:03d}"
            
            if i == 1:  # First device is real
                device_data = {
                    'id': device_id,
                    'name': f"Smart Plug #{i} (Real)",
                    'type': 'Smart Plug',
                    'location': 'Lab Room A',
                    'ip_address': REAL_DEVICE_CONFIG['address'],
                    'tuya_device_id': REAL_DEVICE_CONFIG['dev_id'],
                    'local_key': REAL_DEVICE_CONFIG['local_key'],
                    'is_real': True
                }
                
                devices_data[device_id] = {
                    'id': device_id,
                    'name': device_data['name'],
                    'type': device_data['type'],
                    'location': device_data['location'],
                    'ip_address': device_data['ip_address'],
                    'tuya_device_id': device_data['tuya_device_id'],
                    'local_key': device_data['local_key'],
                    'status': 'online',
                    'state': False,
                    'voltage': 220.0,
                    'current': 0.0,
                    'power': 0.0,
                    'energy': 0.0,
                    'temperature': 25.0,
                    'humidity': 60.0,
                    'last_updated': datetime.now(),
                    'is_real': True,
                    'cost_today': 0.0,
                    'uptime': 0
                }
                save_device_to_db(device_data)
                
            else:  # Simulated devices
                device_types = ['Smart Plug', 'Smart Switch', 'Smart Bulb', 'Smart Fan', 'Smart AC']
                locations = ['Office', 'Lab Room A', 'Lab Room B', 'Conference Room', 'Corridor', 'Library']
                
                device_data = {
                    'id': device_id,
                    'name': f"{random.choice(device_types)} #{i}",
                    'type': random.choice(device_types),
                    'location': random.choice(locations),
                    'is_real': False
                }
                
                devices_data[device_id] = {
                    'id': device_id,
                    'name': device_data['name'],
                    'type': device_data['type'],
                    'location': device_data['location'],
                    'ip_address': None,
                    'tuya_device_id': None,
                    'local_key': None,
                    'status': random.choice(['online', 'online', 'online', 'offline']),
                    'state': random.choice([True, False]),
                    'voltage': round(random.uniform(210, 230), 1),
                    'current': round(random.uniform(0.001, 0.5), 3),
                    'power': round(random.uniform(10, 1500), 1),
                    'energy': round(random.uniform(0, 100), 3),
                    'temperature': round(random.uniform(20, 35), 1),
                    'humidity': round(random.uniform(40, 80), 1),
                    'last_updated': datetime.now(),
                    'is_real': False,
                    'cost_today': round(random.uniform(0, 50), 2),
                    'uptime': random.randint(0, 86400)
                }
                save_device_to_db(device_data)
    
    print(f"✓ Initialized {len(devices_data)} devices")

def get_real_device_data():
    """Get real data from Tuya device with improved error handling"""
    global real_device
    try:
        if not real_device:
            real_device = tinytuya.OutletDevice(
                dev_id=REAL_DEVICE_CONFIG['dev_id'],
                address=REAL_DEVICE_CONFIG['address'],
                local_key=REAL_DEVICE_CONFIG['local_key'],
                version=REAL_DEVICE_CONFIG['version']
            )
            real_device.set_socketTimeout(5)
        
        data = real_device.status()
        print(f"Real device data: {data}")
        
        if 'dps' in data:
            dps = data['dps']
            return {
                'status': 'online',
                'state': dps.get('1', False),
                'voltage': dps.get('20', 2200) / 10.0,
                'current': dps.get('18', 0) / 1000.0,
                'power': dps.get('19', 0) / 10.0,
                'energy': dps.get('17', 0) / 1000.0
            }
        else:
            return {'status': 'offline'}
            
    except Exception as e:
        print(f"Error getting real device data: {e}")
        return {'status': 'offline'}

def update_devices():
    """Update device data periodically"""
    while True:
        try:
            current_time = datetime.now()
            
            # Update real device
            real_data = get_real_device_data()
            if 'device_001' in devices_data:
                device = devices_data['device_001']
                if real_data['status'] == 'online':
                    device['status'] = 'online'
                    device['state'] = real_data['state']
                    device['voltage'] = real_data['voltage']
                    device['current'] = real_data['current']
                    device['power'] = real_data['power']
                    device['energy'] = real_data['energy']
                    device['uptime'] = int((current_time - device_start_time).total_seconds())
                    device['cost_today'] = round(device['energy'] * settings['electricity_rate'], 2)
                    device['last_updated'] = current_time
                else:
                    device['status'] = 'offline'
            
            # Update simulated devices with more realistic behavior
            for device_id, device in devices_data.items():
                if not device['is_real'] and device['status'] == 'online':
                    if device['state']:
                        # Device is ON - consume power
                        base_power = {
                            'Smart Plug': random.uniform(10, 100),
                            'Smart Switch': random.uniform(5, 50),
                            'Smart Bulb': random.uniform(8, 25),
                            'Smart Fan': random.uniform(50, 120),
                            'Smart AC': random.uniform(800, 2000)
                        }.get(device['type'], 50)
                        
                        device['power'] = base_power + random.uniform(-base_power*0.1, base_power*0.1)
                        device['voltage'] = max(200, min(240, device['voltage'] + random.uniform(-1, 1)))
                        device['current'] = device['power'] / device['voltage']
                        device['energy'] += device['power'] * settings['update_interval'] / 3600000  # Convert to kWh
                    else:
                        # Device is OFF - standby power
                        device['current'] = random.uniform(0.001, 0.005)
                        device['power'] = device['voltage'] * device['current']
                        device['energy'] += device['power'] * settings['update_interval'] / 3600000
                    
                    device['cost_today'] = round(device['energy'] * settings['electricity_rate'], 2)
                    device['uptime'] += settings['update_interval']
                    device['last_updated'] = current_time
                    
                    # Randomly change device status occasionally
                    if random.random() < 0.001:  # 0.1% chance per update
                        device['status'] = random.choice(['online', 'offline'])
            
            # Log data and emit updates
            log_data_to_csv()
            save_historical_data_to_db()
            
            try:
                serializable_devices = serialize_device_data(devices_data)
                statistics = calculate_statistics()
                socketio.emit('device_update', {
                    'devices': serializable_devices,
                    'timestamp': current_time.isoformat(),
                    'statistics': statistics
                })
            except Exception as emit_error:
                print(f"Error emitting WebSocket data: {emit_error}")
            
        except Exception as e:
            print(f"Error in update_devices: {e}")
        
        time.sleep(settings['update_interval'])

def calculate_statistics():
    """Calculate dashboard statistics"""
    online_devices = sum(1 for d in devices_data.values() if d['status'] == 'online')
    active_devices = sum(1 for d in devices_data.values() if d['state'] and d['status'] == 'online')
    total_power = sum(d['power'] for d in devices_data.values() if d['status'] == 'online')
    total_cost = sum(d['cost_today'] for d in devices_data.values())
    
    return {
        'total_devices': len(devices_data),
        'online_devices': online_devices,
        'offline_devices': len(devices_data) - online_devices,
        'active_devices': active_devices,
        'total_power': round(total_power, 2),
        'total_cost': round(total_cost, 2)
    }

def log_data_to_csv():
    """Log device data to CSV files with size management"""
    try:
        os.makedirs('data', exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H')
        filename = f'data/iot_data_{timestamp}.csv'
        
        # Check file size and create new file if needed
        if os.path.exists(filename):
            file_size_mb = os.path.getsize(filename) / (1024 * 1024)
            if file_size_mb >= settings['file_size_limit']:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f'data/iot_data_{timestamp}.csv'
        
        file_exists = os.path.exists(filename)
        
        with open(filename, 'a', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['timestamp', 'device_id', 'name', 'status', 'state', 'voltage', 'current', 'power', 'energy', 'cost']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            if not file_exists:
                writer.writeheader()
            
            for device_id, device in devices_data.items():
                writer.writerow({
                    'timestamp': datetime.now().isoformat(),
                    'device_id': device_id,
                    'name': device['name'],
                    'status': device['status'],
                    'state': device['state'],
                    'voltage': device['voltage'],
                    'current': device['current'],
                    'power': device['power'],
                    'energy': device['energy'],
                    'cost': device['cost_today']
                })
                
    except Exception as e:
        print(f"Error logging data: {e}")

def save_historical_data_to_db():
    """Save historical data to database"""
    try:
        conn = sqlite3.connect('iot_dashboard.db')
        cursor = conn.cursor()
        
        for device_id, device in devices_data.items():
            cursor.execute('''
                INSERT INTO historical_data 
                (device_id, voltage, current, power, energy, cost)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                device_id, device['voltage'], device['current'],
                device['power'], device['energy'], device['cost_today']
            ))
        
        # Clean old data (keep only last 7 days)
        week_ago = datetime.now() - timedelta(days=7)
        cursor.execute('DELETE FROM historical_data WHERE timestamp < ?', (week_ago,))
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        print(f"Error saving historical data: {e}")

# Flask Routes
@app.route('/')
def dashboard():
    return send_from_directory('.', 'index.html')

@app.route('/api/devices')
def get_devices():
    serializable_devices = serialize_device_data(devices_data)
    return jsonify({
        'devices': serializable_devices,
        'timestamp': datetime.now().isoformat(),
        'statistics': calculate_statistics()
    })

@app.route('/api/devices', methods=['POST'])
def add_device():
    try:
        data = request.get_json()
        device_id = get_next_device_id()
        
        # Validate input
        if not data.get('name') or not data.get('type') or not data.get('location'):
            return jsonify({'success': False, 'error': 'Name, type, and location are required'}), 400
        
        # Create new device
        device_data = {
            'id': device_id,
            'name': data['name'],
            'type': data['type'],
            'location': data['location'],
            'ip_address': data.get('ip_address'),
            'tuya_device_id': data.get('device_id'),
            'local_key': data.get('local_key'),
            'is_real': bool(data.get('device_id') and data.get('local_key'))
        }
        
        devices_data[device_id] = {
            'id': device_id,
            'name': device_data['name'],
            'type': device_data['type'],
            'location': device_data['location'],
            'ip_address': device_data['ip_address'],
            'tuya_device_id': device_data['tuya_device_id'],
            'local_key': device_data['local_key'],
            'status': 'online' if device_data['is_real'] else random.choice(['online', 'offline']),
            'state': False,
            'voltage': 220.0,
            'current': 0.0,
            'power': 0.0,
            'energy': 0.0,
            'temperature': 25.0,
            'humidity': 60.0,
            'last_updated': datetime.now(),
            'is_real': device_data['is_real'],
            'cost_today': 0.0,
            'uptime': 0
        }
        
        save_device_to_db(device_data)
        
        return jsonify({
            'success': True,
            'device_id': device_id,
            'message': 'Device added successfully'
        })
        
    except Exception as e:
        print(f"Error adding device: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/devices/<device_id>', methods=['PUT'])
def update_device(device_id):
    try:
        if device_id not in devices_data:
            return jsonify({'success': False, 'error': 'Device not found'}), 404
        
        data = request.get_json()
        device = devices_data[device_id]
        
        # Validate input
        if not data.get('name') or not data.get('type') or not data.get('location'):
            return jsonify({'success': False, 'error': 'Name, type, and location are required'}), 400
        
        # Update device data
        device['name'] = data['name']
        device['type'] = data['type']
        device['location'] = data['location']
        device['last_updated'] = datetime.now()
        
        # Update in database
        device_data = {
            'id': device_id,
            'name': data['name'],
            'type': data['type'],
            'location': data['location'],
            'ip_address': device.get('ip_address'),
            'tuya_device_id': device.get('tuya_device_id'),
            'local_key': device.get('local_key'),
            'is_real': device['is_real']
        }
        save_device_to_db(device_data)
        
        return jsonify({
            'success': True,
            'message': 'Device updated successfully'
        })
        
    except Exception as e:
        print(f"Error updating device: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/devices/<device_id>', methods=['DELETE'])
def delete_device(device_id):
    try:
        if device_id not in devices_data:
            return jsonify({'success': False, 'error': 'Device not found'}), 404
        
        # Don't allow deletion of real device
        if devices_data[device_id]['is_real']:
            return jsonify({'success': False, 'error': 'Cannot delete real device'}), 400
        
        del devices_data[device_id]
        delete_device_from_db(device_id)
        
        return jsonify({
            'success': True,
            'message': 'Device deleted successfully'
        })
        
    except Exception as e:
        print(f"Error deleting device: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/devices/<device_id>/control', methods=['POST'])
def control_device(device_id):
    try:
        data = request.get_json()
        action = data.get('action')
        
        if device_id not in devices_data:
            return jsonify({'success': False, 'error': 'Device not found'}), 404
        
        if action not in ['on', 'off']:
            return jsonify({'success': False, 'error': 'Invalid action. Use "on" or "off"'}), 400
        
        device = devices_data[device_id]
        
        if device['is_real'] and real_device:
            try:
                if action == 'on':
                    result = real_device.turn_on()
                    device['state'] = True
                elif action == 'off':
                    result = real_device.turn_off()
                    device['state'] = False
                
                device['last_updated'] = datetime.now()
                
                return jsonify({
                    'success': True,
                    'device_id': device_id,
                    'action': action,
                    'new_state': device['state']
                })
            except Exception as e:
                print(f"Error controlling real device: {e}")
                return jsonify({'success': False, 'error': f'Failed to control real device: {str(e)}'}), 500
        else:
            # Simulated device
            device['state'] = (action == 'on')
            device['last_updated'] = datetime.now()
            return jsonify({
                'success': True,
                'device_id': device_id,
                'action': action,
                'new_state': device['state']
            })
            
    except Exception as e:
        print(f"Error controlling device: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/devices/<device_id>/history')
def get_device_history(device_id):
    """Get historical data for device charts"""
    try:
        if device_id not in devices_data:
            return jsonify({'success': False, 'error': 'Device not found'}), 404
            
        start_date = request.args.get('start')
        end_date = request.args.get('end')
        
        conn = sqlite3.connect('iot_dashboard.db')
        cursor = conn.cursor()
        
        query = '''
            SELECT timestamp, voltage, current, power, energy 
            FROM historical_data 
            WHERE device_id = ?
        '''
        params = [device_id]
        
        if start_date and end_date:
            query += ' AND timestamp BETWEEN ? AND ?'
            params.extend([start_date, end_date])
        
        query += ' ORDER BY timestamp DESC LIMIT 100'
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        history = []
        for row in rows:
            history.append({
                'timestamp': row[0],
                'voltage': row[1] or 0,
                'current': row[2] or 0,
                'power': row[3] or 0,
                'energy': row[4] or 0
            })
        
        return jsonify({
            'device_id': device_id,
            'history': list(reversed(history)),
            'count': len(history)
        })
        
    except Exception as e:
        print(f"Error getting device history: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/devices/<device_id>/export')
def export_device_csv(device_id):
    """Export individual device data as CSV"""
    try:
        if device_id not in devices_data:
            return jsonify({'error': 'Device not found'}), 404
        
        start_date = request.args.get('start')
        end_date = request.args.get('end')
        
        conn = sqlite3.connect('iot_dashboard.db')
        cursor = conn.cursor()
        
        query = '''
            SELECT timestamp, voltage, current, power, energy, cost
            FROM historical_data 
            WHERE device_id = ?
        '''
        params = [device_id]
        
        if start_date and end_date:
            query += ' AND timestamp BETWEEN ? AND ?'
            params.extend([start_date, end_date])
        
        query += ' ORDER BY timestamp'
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return jsonify({'error': 'No data available for this device'}), 404
        
        # Create CSV content
        import io
        output = io.StringIO()
        fieldnames = ['timestamp', 'voltage', 'current', 'power', 'energy', 'cost']
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        
        for row in rows:
            writer.writerow({
                'timestamp': row[0],
                'voltage': row[1] or 0,
                'current': row[2] or 0,
                'power': row[3] or 0,
                'energy': row[4] or 0,
                'cost': row[5] or 0
            })
        
        device_name = devices_data[device_id]['name'].replace(' ', '_').replace('#', '').replace('/', '_')
        filename = f"{device_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename={filename}'}
        )
        
    except Exception as e:
        print(f"Error exporting device data: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/export/all')
def export_all_data():
    """Export all device data as CSV"""
    try:
        conn = sqlite3.connect('iot_dashboard.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT hd.timestamp, d.name, d.location, d.type, 
                   hd.voltage, hd.current, hd.power, hd.energy, hd.cost
            FROM historical_data hd
            JOIN devices d ON hd.device_id = d.id
            ORDER BY hd.timestamp
        ''')
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return jsonify({'error': 'No data available'}), 404
        
        import io
        output = io.StringIO()
        fieldnames = ['timestamp', 'device_name', 'location', 'type', 'voltage', 'current', 'power', 'energy', 'cost']
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        
        for row in rows:
            writer.writerow({
                'timestamp': row[0],
                'device_name': row[1],
                'location': row[2],
                'type': row[3],
                'voltage': row[4] or 0,
                'current': row[5] or 0,
                'power': row[6] or 0,
                'energy': row[7] or 0,
                'cost': row[8] or 0
            })
        
        filename = f"all_devices_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename={filename}'}
        )
        
    except Exception as e:
        print(f"Error exporting all data: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings')
def get_settings():
    return jsonify(settings)

@app.route('/api/settings', methods=['POST'])
def update_settings():
    try:
        global settings
        data = request.get_json()
        
        # Validate settings
        new_rate = data.get('electricity_rate')
        new_interval = data.get('update_interval')
        new_limit = data.get('file_size_limit')
        
        if new_rate is not None:
            if new_rate <= 0:
                return jsonify({'success': False, 'error': 'Electricity rate must be positive'}), 400
            settings['electricity_rate'] = float(new_rate)
        
        if new_interval is not None:
            if not (1 <= new_interval <= 10):
                return jsonify({'success': False, 'error': 'Update interval must be between 1 and 10 seconds'}), 400
            settings['update_interval'] = int(new_interval)
        
        if new_limit is not None:
            if not (1 <= new_limit <= 10):
                return jsonify({'success': False, 'error': 'File size limit must be between 1 and 10 MB'}), 400
            settings['file_size_limit'] = int(new_limit)
        
        save_settings_to_db()
        
        return jsonify({
            'success': True,
            'message': 'Settings updated successfully',
            'settings': settings
        })
        
    except Exception as e:
        print(f"Error updating settings: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/system/status')
def get_system_status():
    """Get system status and health"""
    try:
        online_devices = sum(1 for d in devices_data.values() if d['status'] == 'online')
        total_devices = len(devices_data)
        
        # Check disk space
        import shutil
        disk_usage = shutil.disk_usage('.')
        free_space_gb = disk_usage.free / (1024**3)
        
        # Check database size
        db_size = 0
        if os.path.exists('iot_dashboard.db'):
            db_size = os.path.getsize('iot_dashboard.db') / (1024**2)  # MB
        
        return jsonify({
            'status': 'healthy',
            'devices': {
                'total': total_devices,
                'online': online_devices,
                'offline': total_devices - online_devices
            },
            'system': {
                'free_space_gb': round(free_space_gb, 2),
                'database_size_mb': round(db_size, 2),
                'uptime_seconds': int((datetime.now() - device_start_time).total_seconds())
            },
            'settings': settings
        })
        
    except Exception as e:
        print(f"Error getting system status: {e}")
        return jsonify({'error': str(e)}), 500

@socketio.on('connect')
def handle_connect():
    print(f'Client connected: {request.sid}')
    # Send current device data to newly connected client
    serializable_devices = serialize_device_data(devices_data)
    emit('device_update', {
        'devices': serializable_devices,
        'timestamp': datetime.now().isoformat(),
        'statistics': calculate_statistics()
    })

@socketio.on('disconnect')
def handle_disconnect():
    print(f'Client disconnected: {request.sid}')

@socketio.on('ping')
def handle_ping():
    emit('pong', {'timestamp': datetime.now().isoformat()})

if __name__ == '__main__':
    print("=" * 80)
    print("CSE407 IoT Energy Monitoring Dashboard")
    print("By Md Maruf Hasan | ID: 2021-3-60-101")
    print("Dynamic IoT Dashboard for Real-time Device Monitoring and Control")
    print("=" * 80)
    
    # Initialize database and load data
    print("🔧 Initializing system...")
    init_database()
    load_settings_from_db()
    initialize_devices()
    
    print(f"✓ Database initialized")
    print(f"✓ {len(devices_data)} devices loaded")
    print(f"✓ Electricity rate: ৳{settings['electricity_rate']}/kWh")
    print(f"✓ Update interval: {settings['update_interval']} second(s)")
    print(f"✓ CSV file size limit: {settings['file_size_limit']}MB")
    
    # Start background thread for device updates
    print("🔄 Starting background processes...")
    update_thread = threading.Thread(target=update_devices, daemon=True)
    update_thread.start()
    print("✓ Device update thread started")
    
    print("=" * 80)
    print("🚀 Starting server...")
    print("📊 Dashboard will be available at:")
    print("   • Local: http://localhost:5000")
    print("   • Network: http://[your-ip]:5000")
    print("\n🌐 For internet access, use one of these methods:")
    print("   • ngrok: ngrok http 5000")
    print("   • LocalTunnel: lt --port 5000")
    print("   • Port forwarding on your router")
    print("\n📝 Features:")
    print("   ✅ Real-time monitoring of 100+ devices")
    print("   ✅ Historical data visualization")
    print("   ✅ Real-time billing calculation") 
    print("   ✅ CSV data export")
    print("   ✅ Device control & management")
    print("   ✅ WebSocket real-time updates")
    print("   ✅ Responsive design")
    print("   ✅ RESTful API")
    print("=" * 80)
    
    # Run the app
    try:
        socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user")
    except Exception as e:
        print(f"\n❌ Server error: {e}")
    finally:
        print("👋 Goodbye!")
