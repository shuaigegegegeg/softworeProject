import requests
import json
import tempfile
import os
import webbrowser
import threading
import time
import hmac
import hashlib
from typing import Optional, Dict, Any, Callable


class NavigationModule:
    def __init__(self, command_callback: Callable[[str, str], None]):
        """
        初始化导航模块

        Args:
            command_callback: 回调函数，参数为(command_type, command_text)
        """
        self.command_callback = command_callback

        # 腾讯地图API配置
        self.api_key = "3O4BZ-Y2HK7-KILXI-HW5HL-SA7OF-KSB6D"
        self.secret_key = "by490BcRhbv3C349C0BzMgdAV9Nwz8VV"
        self.base_url = "https://apis.map.qq.com"

        # 硬编码位置（天津某位置）
        self.hardcoded_lat = 38.98906
        self.hardcoded_lng = 117.347653

        # 当前位置和导航状态
        self.current_location = None
        self.destination = None
        self.route_data = None
        self.is_navigating = False

        # 地图HTML文件路径
        self.map_html_path = None

        # 添加API调用限制
        self.last_api_call_time = 0
        self.api_call_interval = 1.0  # 最小调用间隔（秒）

        print("🗺️ 导航模块已初始化")

        # 启动时自动设置当前位置
        self.initialize_location()

    def _check_api_rate_limit(self):
        """检查API调用频率限制"""
        current_time = time.time()
        if current_time - self.last_api_call_time < self.api_call_interval:
            wait_time = self.api_call_interval - (current_time - self.last_api_call_time)
            print(f"⏱️ API调用频率限制，等待 {wait_time:.2f} 秒...")
            time.sleep(wait_time)
        self.last_api_call_time = time.time()

    def _generate_signature(self, path, params):
        """
        生成请求签名

        Args:
            path (str): API路径
            params (dict): 请求参数

        Returns:
            str: 签名字符串
        """
        if not self.secret_key:
            return None

        try:
            # 按字典序排序参数
            sorted_params = sorted(params.items())

            # 构建查询字符串
            query_string = '&'.join([f"{k}={v}" for k, v in sorted_params])

            # 构建签名原文：请求路径 + ? + 查询字符串 + SK密钥
            sign_str = f"{path}?{query_string}{self.secret_key}"

            # 使用MD5计算签名
            signature = hashlib.md5(sign_str.encode('utf-8')).hexdigest()

            return signature
        except Exception as e:
            print(f"❌ 生成签名失败: {e}")
            return None

    def initialize_location(self):
        """初始化当前位置"""
        try:
            print("🎯 正在初始化当前位置...")

            # 优先使用硬编码位置
            if self.hardcoded_lat and self.hardcoded_lng:
                print("📍 使用硬编码位置...")
                self.set_hardcoded_location(self.hardcoded_lat, self.hardcoded_lng)
            else:
                print("📍 使用IP定位...")
                self.get_current_location_by_ip()

            # 生成默认地图
            if self.current_location:
                self.generate_default_map()

        except Exception as e:
            print(f"❌ 位置初始化失败: {e}")

    def set_hardcoded_location(self, lat, lng):
        """设置硬编码位置"""
        try:
            # 验证坐标范围（中国境内）
            if not (18 <= lat <= 54 and 73 <= lng <= 135):
                print("⚠️  警告：坐标超出中国境内范围，请检查是否正确")

            # 通过逆地址解析获取地址名称
            address = self.reverse_geocode(lat, lng)
            if address:
                self.current_location = {
                    'lat': lat,
                    'lng': lng,
                    'address': address
                }
                print(f"✅ 硬编码位置设置成功")
                print(f"📍 地址: {address}")
                print(f"📐 坐标: ({lat:.6f}, {lng:.6f})")
            else:
                self.current_location = {
                    'lat': lat,
                    'lng': lng,
                    'address': f"位置({lat:.6f}, {lng:.6f})"
                }
                print(f"✅ 硬编码位置设置成功（无法获取详细地址）")

            return True
        except Exception as e:
            print(f"❌ 设置硬编码位置失败: {e}")
            return False

    def get_current_location_by_ip(self):
        """通过IP获取当前位置"""
        try:
            self._check_api_rate_limit()

            path = "/ws/location/v1/ip"
            params = {
                'key': self.api_key,
                'output': 'json'
            }

            # 生成签名
            if self.secret_key:
                signature = self._generate_signature(path, params)
                if signature:
                    params['sig'] = signature

            url = self.base_url + path
            response = requests.get(url, params=params, timeout=10)
            data = response.json()

            if data and data.get('status') == 0:
                location = data['result']['location']
                address = data['result']['ad_info']
                self.current_location = {
                    'lat': location['lat'],
                    'lng': location['lng'],
                    'address': f"{address['province']}{address['city']}{address['district']}"
                }
                print(f"✅ IP定位成功: {self.current_location['address']}")
                return True
            else:
                print(f"❌ IP定位失败: {data.get('message', '未知错误') if data else '请求失败'}")
                return False

        except Exception as e:
            print(f"❌ IP定位失败: {e}")
            return False

    def reverse_geocode(self, lat, lng):
        """逆地址解析"""
        try:
            self._check_api_rate_limit()

            path = "/ws/geocoder/v1/"
            params = {
                'location': f"{lat},{lng}",
                'key': self.api_key,
                'output': 'json',
                'get_poi': 1
            }

            # 生成签名
            if self.secret_key:
                signature = self._generate_signature(path, params)
                if signature:
                    params['sig'] = signature

            url = self.base_url + path
            response = requests.get(url, params=params, timeout=10)
            data = response.json()

            if data and data.get('status') == 0:
                result = data['result']
                if 'address' in result:
                    return result['address']
                elif 'formatted_addresses' in result and 'recommend' in result['formatted_addresses']:
                    return result['formatted_addresses']['recommend']

            return None
        except Exception as e:
            print(f"❌ 逆地址解析失败: {e}")
            return None

    def search_place(self, keyword):
        """搜索地点"""
        if not self.current_location:
            print("❌ 当前位置未设置，无法搜索")
            return []

        try:
            self._check_api_rate_limit()

            path = "/ws/place/v1/search"
            boundary = f"nearby({self.current_location['lat']},{self.current_location['lng']},50000)"

            params = {
                'keyword': keyword,
                'boundary': boundary,
                'key': self.api_key,
                'output': 'json',
                'page_size': 5,
                'page_index': 0,
                'orderby': '_distance'
            }

            # 生成签名
            if self.secret_key:
                signature = self._generate_signature(path, params)
                if signature:
                    params['sig'] = signature

            url = self.base_url + path
            response = requests.get(url, params=params, timeout=10)
            data = response.json()

            if data and data.get('status') == 0:
                return data.get('data', [])
            else:
                error_msg = data.get('message', '未知错误') if data else '请求失败'
                print(f"❌ 搜索失败: {error_msg}")

                # 如果是API限制错误，增加等待时间
                if "上限" in error_msg or "limit" in error_msg.lower():
                    print("⏱️ 检测到API限制，等待更长时间...")
                    time.sleep(5)  # 等待5秒

                return []

        except Exception as e:
            print(f"❌ 搜索失败: {e}")
            return []

    def get_route(self, destination_lat, destination_lng):
        """获取路线规划"""
        if not self.current_location:
            print("❌ 当前位置未设置，无法规划路线")
            return None

        try:
            self._check_api_rate_limit()

            path = "/ws/direction/v1/driving/"
            params = {
                'from': f"{self.current_location['lat']},{self.current_location['lng']}",
                'to': f"{destination_lat},{destination_lng}",
                'key': self.api_key,
                'output': 'json'
            }

            # 生成签名
            if self.secret_key:
                signature = self._generate_signature(path, params)
                if signature:
                    params['sig'] = signature

            url = self.base_url + path
            response = requests.get(url, params=params, timeout=15)
            data = response.json()

            print(f"🔍 API请求URL: {url}")
            print(f"📥 API响应数据: {json.dumps(data, ensure_ascii=False, indent=2)}")

            if data and data.get('status') == 0:
                return data.get('result')
            else:
                error_msg = data.get('message', '未知错误') if data else '请求失败'
                print(f"❌ 路线规划失败: {error_msg}")

                # 如果是API限制错误，增加等待时间
                if "上限" in error_msg or "limit" in error_msg.lower():
                    print("⏱️ 检测到API限制，等待更长时间...")
                    time.sleep(5)

                return None

        except Exception as e:
            print(f"❌ 路线规划失败: {e}")
            return None

    def start_navigation(self, destination_keyword):
        """开始导航"""
        try:
            print(f"🧭 开始导航到: {destination_keyword}")

            # 搜索目的地
            places = self.search_place(destination_keyword)
            if not places:
                # 不要通过回调发送导航失败消息，而是直接返回
                print(f"❌ 未找到地点: {destination_keyword}")
                return False

            # 选择第一个结果
            destination = places[0]
            dest_lat = destination['location']['lat']
            dest_lng = destination['location']['lng']
            dest_name = destination['title']
            dest_address = destination['address']

            print(f"📍 找到目的地: {dest_name}")
            print(f"📍 地址: {dest_address}")

            # 获取路线
            route_data = self.get_route(dest_lat, dest_lng)
            if not route_data:
                print(f"❌ 无法规划到 {dest_name} 的路线")
                return False

            # 保存导航信息
            self.destination = {
                'lat': dest_lat,
                'lng': dest_lng,
                'name': dest_name,
                'address': dest_address
            }
            self.route_data = route_data
            self.is_navigating = True

            # 生成导航地图
            self.generate_navigation_map()

            # 获取路线信息 - 修复时间单位问题
            if 'routes' in route_data and route_data['routes']:
                route = route_data['routes'][0]
                distance_km = route['distance'] / 1000

                # 修复：腾讯地图API返回的duration已经是分钟，不需要再除以60
                duration_min = route['duration']  # 直接使用，因为API返回的就是分钟

                print(f"📊 路线详情:")
                print(f"   距离: {distance_km:.1f}公里")
                print(f"   时间: {duration_min:.0f}分钟")
                print(f"   原始数据: distance={route['distance']}米, duration={route['duration']}分钟")

                result_msg = f"导航开始: 到{dest_name}，距离{distance_km:.1f}公里，预计{duration_min:.0f}分钟"
                print(f"✅ {result_msg}")

                return True
            else:
                print(f"❌ 路线数据异常")
                return False

        except Exception as e:
            print(f"❌ 导航启动失败: {e}")
            return False

    def stop_navigation(self):
        """停止导航"""
        try:
            self.destination = None
            self.route_data = None
            self.is_navigating = False

            # 生成默认地图
            self.generate_default_map()

            print("🛑 导航已停止")
            return True

        except Exception as e:
            print(f"❌ 停止导航失败: {e}")
            return False

    def generate_default_map(self):
        """生成默认地图（仅显示当前位置）"""
        if not self.current_location:
            return

        try:
            html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>车载导航系统</title>
    <style>
        body {{
            margin: 0;
            padding: 0;
            font-family: Arial, sans-serif;
            background: #000;
        }}
        #map-container {{
            width: 100%;
            height: 100vh;
            position: relative;
        }}
        .map-overlay {{
            position: absolute;
            top: 10px;
            left: 10px;
            right: 10px;
            background: rgba(0, 0, 0, 0.8);
            color: white;
            padding: 10px;
            border-radius: 8px;
            z-index: 1000;
            font-size: 14px;
        }}
        .status-ready {{
            color: #00ff88;
        }}
        .loading {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            color: white;
            font-size: 18px;
            z-index: 1001;
        }}
    </style>
</head>
<body>
    <div id="map-container">
        <div class="loading" id="loadingText">地图加载中...</div>
        <div class="map-overlay">
            <div class="status-ready">🗺️ 导航系统就绪</div>
            <div>📍 当前位置: {self.current_location['address']}</div>
            <div>💬 请语音说出"导航到 [地点名称]"开始导航</div>
        </div>
    </div>

    <script src="https://map.qq.com/api/gljs?v=1.exp&key={self.api_key}"></script>
    <script>
        let map;

        function initMap() {{
            try {{
                console.log('开始初始化地图...');
                const center = new TMap.LatLng({self.current_location['lat']}, {self.current_location['lng']});

                map = new TMap.Map('map-container', {{
                    center: center,
                    zoom: 15,
                    pitch: 0,
                    rotation: 0,
                    mapStyleId: 'style1'
                }});

                // 添加当前位置标记
                const currentMarker = new TMap.MultiMarker({{
                    map: map,
                    geometries: [{{
                        position: center,
                        id: 'current'
                    }}],
                    styles: {{
                        'current': new TMap.MarkerStyle({{
                            width: 30,
                            height: 40,
                            anchor: {{ x: 15, y: 40 }},
                            src: 'data:image/svg+xml;base64,' + btoa('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#00ff88"><circle cx="12" cy="12" r="8" stroke="#fff" stroke-width="2"/><circle cx="12" cy="12" r="3" fill="#fff"/></svg>')
                        }})
                    }}
                }});

                // 隐藏加载文本
                const loadingText = document.getElementById('loadingText');
                if (loadingText) {{
                    loadingText.style.display = 'none';
                }}

                console.log('地图初始化完成');
            }} catch (error) {{
                console.error('地图初始化失败:', error);
                const loadingText = document.getElementById('loadingText');
                if (loadingText) {{
                    loadingText.textContent = '地图加载失败';
                    loadingText.style.color = '#ff4444';
                }}
            }}
        }}

        // 页面加载完成后初始化地图
        window.onload = function() {{
            console.log('页面加载完成，开始初始化地图');
            setTimeout(initMap, 1000); // 延迟1秒确保所有资源加载完成
        }};

        // 添加错误处理
        window.onerror = function(msg, url, line, col, error) {{
            console.error('页面错误:', msg, url, line, col, error);
            const loadingText = document.getElementById('loadingText');
            if (loadingText) {{
                loadingText.textContent = '地图加载出错';
                loadingText.style.color = '#ff4444';
            }}
        }};
    </script>
</body>
</html>
            """

            # 保存到临时文件
            if self.map_html_path:
                try:
                    os.unlink(self.map_html_path)
                except:
                    pass

            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
                f.write(html_content)
                self.map_html_path = f.name

            print(f"🗺️ 默认地图已生成: {self.map_html_path}")

        except Exception as e:
            print(f"❌ 生成默认地图失败: {e}")

    def generate_navigation_map(self):
        """生成导航地图"""
        if not self.current_location or not self.destination or not self.route_data:
            return

        try:
            # 获取路线信息 - 修复时间单位问题
            route = self.route_data['routes'][0] if 'routes' in self.route_data and self.route_data['routes'] else None
            if not route:
                return

            distance_km = route['distance'] / 1000
            # 修复：腾讯地图API返回的duration已经是分钟，不需要再除以60
            duration_min = route['duration']  # 直接使用分钟数

            # 处理路线数据
            route_points_str = "[]"  # 默认空路线
            if 'polyline' in route:
                route_points_str = self._process_polyline_data(route['polyline'])

            html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>车载导航 - {self.destination['name']}</title>
    <style>
        body {{
            margin: 0;
            padding: 0;
            font-family: Arial, sans-serif;
            background: #000;
        }}
        #map-container {{
            width: 100%;
            height: 100vh;
            position: relative;
        }}
        .nav-overlay {{
            position: absolute;
            top: 10px;
            left: 10px;
            right: 10px;
            background: rgba(0, 123, 186, 0.9);
            color: white;
            padding: 12px;
            border-radius: 8px;
            z-index: 1000;
            font-size: 14px;
        }}
        .nav-header {{
            font-size: 16px;
            font-weight: bold;
            color: #00ff88;
            margin-bottom: 5px;
        }}
        .nav-info {{
            display: flex;
            justify-content: space-between;
            margin-bottom: 8px;
        }}
        .stop-btn {{
            position: absolute;
            bottom: 20px;
            right: 20px;
            background: #ff4444;
            color: white;
            border: none;
            padding: 12px 20px;
            border-radius: 8px;
            cursor: pointer;
            z-index: 1000;
            font-size: 14px;
        }}
        .loading {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            color: white;
            font-size: 18px;
            z-index: 1001;
        }}
    </style>
</head>
<body>
    <div id="map-container">
        <div class="loading" id="loadingText">导航地图加载中...</div>
        <div class="nav-overlay">
            <div class="nav-header">🧭 正在导航至 {self.destination['name']}</div>
            <div class="nav-info">
                <span>📏 {distance_km:.1f}公里</span>
                <span>⏱️ {duration_min:.0f}分钟</span>
            </div>
            <div>📍 {self.destination['address']}</div>
        </div>
        <button class="stop-btn" onclick="stopNavigation()">🛑 停止导航</button>
    </div>

    <script src="https://map.qq.com/api/gljs?v=1.exp&key={self.api_key}"></script>
    <script>
        let map;
        let routeLayer;

        const routePoints = {route_points_str};

        function initMap() {{
            try {{
                console.log('开始初始化导航地图...');
                const center = new TMap.LatLng({(self.current_location['lat'] + self.destination['lat']) / 2}, {(self.current_location['lng'] + self.destination['lng']) / 2});

                map = new TMap.Map('map-container', {{
                    center: center,
                    zoom: 13,
                    pitch: 0,
                    rotation: 0,
                    mapStyleId: 'style1'
                }});

                // 添加起点和终点标记
                const markers = new TMap.MultiMarker({{
                    map: map,
                    geometries: [
                        {{
                            position: new TMap.LatLng({self.current_location['lat']}, {self.current_location['lng']}),
                            id: 'start'
                        }},
                        {{
                            position: new TMap.LatLng({self.destination['lat']}, {self.destination['lng']}),
                            id: 'end'
                        }}
                    ],
                    styles: {{
                        'start': new TMap.MarkerStyle({{
                            width: 25,
                            height: 35,
                            anchor: {{ x: 12, y: 35 }},
                            src: 'data:image/svg+xml;base64,' + btoa('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#00ff88"><circle cx="12" cy="12" r="8" stroke="#fff" stroke-width="2"/><circle cx="12" cy="12" r="3" fill="#fff"/></svg>')
                        }}),
                        'end': new TMap.MarkerStyle({{
                            width: 25,
                            height: 35,
                            anchor: {{ x: 12, y: 35 }},
                            src: 'data:image/svg+xml;base64,' + btoa('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#ff4444"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/></svg>')
                        }})
                    }}
                }});

                // 显示路线
                if (routePoints && routePoints.length > 0) {{
                    console.log('显示路线，点数:', routePoints.length);
                    routeLayer = new TMap.MultiPolyline({{
                        map: map,
                        geometries: [{{
                            paths: routePoints,
                            style: 'route'
                        }}],
                        styles: {{
                            'route': new TMap.PolylineStyle({{
                                color: '#007cba',
                                width: 6,
                                borderWidth: 2,
                                borderColor: '#ffffff',
                                lineCap: 'round'
                            }})
                        }}
                    }});

                    // 调整视野
                    const bounds = new TMap.LatLngBounds();
                    routePoints.forEach(point => bounds.extend(point));
                    map.fitBounds(bounds, {{ padding: 50 }});
                }} else {{
                    console.log('无路线数据，显示直线');
                    // 无路线数据时显示直线
                    const line = new TMap.MultiPolyline({{
                        map: map,
                        geometries: [{{
                            paths: [
                                new TMap.LatLng({self.current_location['lat']}, {self.current_location['lng']}),
                                new TMap.LatLng({self.destination['lat']}, {self.destination['lng']})
                            ],
                            style: 'line'
                        }}],
                        styles: {{
                            'line': new TMap.PolylineStyle({{
                                color: '#ff6600',
                                width: 4,
                                lineCap: 'round',
                                dashArray: [10, 10]
                            }})
                        }}
                    }});

                    // 调整视野包含两个点
                    const bounds = new TMap.LatLngBounds();
                    bounds.extend(new TMap.LatLng({self.current_location['lat']}, {self.current_location['lng']}));
                    bounds.extend(new TMap.LatLng({self.destination['lat']}, {self.destination['lng']}));
                    map.fitBounds(bounds, {{ padding: 50 }});
                }}

                // 隐藏加载文本
                const loadingText = document.getElementById('loadingText');
                if (loadingText) {{
                    loadingText.style.display = 'none';
                }}

                console.log('导航地图初始化完成');
                console.log('路线信息: 距离{distance_km:.1f}公里, 时间{duration_min:.0f}分钟');
            }} catch (error) {{
                console.error('导航地图初始化失败:', error);
                const loadingText = document.getElementById('loadingText');
                if (loadingText) {{
                    loadingText.textContent = '导航地图加载失败';
                    loadingText.style.color = '#ff4444';
                }}
            }}
        }}

        function stopNavigation() {{
            // 通过API停止导航
            fetch('/api/stop_navigation', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }}
            }}).then(response => response.json())
              .then(data => console.log('Navigation stopped:', data))
              .catch(error => console.error('Error:', error));
        }}

        // 页面加载完成后初始化地图
        window.onload = function() {{
            console.log('导航页面加载完成，开始初始化地图');
            setTimeout(initMap, 1000); // 延迟1秒确保所有资源加载完成
        }};

        // 添加错误处理
        window.onerror = function(msg, url, line, col, error) {{
            console.error('导航页面错误:', msg, url, line, col, error);
            const loadingText = document.getElementById('loadingText');
            if (loadingText) {{
                loadingText.textContent = '导航地图加载出错';
                loadingText.style.color = '#ff4444';
            }}
        }};
    </script>
</body>
</html>
            """

            # 保存到临时文件
            if self.map_html_path:
                try:
                    os.unlink(self.map_html_path)
                except:
                    pass

            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
                f.write(html_content)
                self.map_html_path = f.name

            print(f"🗺️ 导航地图已生成: {self.destination['name']} -> {self.map_html_path}")
            print(f"📊 显示信息: 距离{distance_km:.1f}公里, 时间{duration_min:.0f}分钟")

        except Exception as e:
            print(f"❌ 生成导航地图失败: {e}")

    def _process_polyline_data(self, polyline_data):
        """处理路线数据"""
        try:
            route_points_js = []

            if isinstance(polyline_data, list) and len(polyline_data) > 0:
                if isinstance(polyline_data[0], dict) and 'lat' in polyline_data[0] and 'lng' in polyline_data[0]:
                    for point in polyline_data:
                        route_points_js.append(f"new TMap.LatLng({point['lat']}, {point['lng']})")
                    return "[" + ", ".join(route_points_js) + "]"
                elif isinstance(polyline_data[0], (int, float)):
                    decoded_points = self._decode_polyline(polyline_data)
                    for point in decoded_points:
                        route_points_js.append(f"new TMap.LatLng({point[0]}, {point[1]})")
                    return "[" + ", ".join(route_points_js) + "]"

            return "[]"
        except Exception as e:
            print(f"❌ 处理路线数据失败: {e}")
            return "[]"

    def _decode_polyline(self, encoded_points):
        """解码路线数据"""
        try:
            if len(encoded_points) < 2:
                return []

            decoded = []
            lat = encoded_points[0]
            lng = encoded_points[1]
            decoded.append([lat, lng])

            for i in range(2, len(encoded_points), 2):
                if i + 1 < len(encoded_points):
                    lat += encoded_points[i] / 1000000.0
                    lng += encoded_points[i + 1] / 1000000.0
                    decoded.append([lat, lng])

            return decoded
        except Exception as e:
            print(f"❌ 解码路线数据失败: {e}")
            return []

    def get_map_url(self):
        """获取地图HTML文件的URL"""
        if self.map_html_path and os.path.exists(self.map_html_path):
            return 'file://' + os.path.abspath(self.map_html_path)
        return None

    def get_navigation_status(self):
        """获取导航状态 - 修复时间显示问题"""
        distance = 0
        duration = 0

        if self.route_data and 'routes' in self.route_data and self.route_data['routes']:
            route = self.route_data['routes'][0]
            distance = f"{route['distance'] / 1000:.1f}公里"

            # 修复：腾讯地图API返回的duration已经是分钟，不需要再除以60
            duration_minutes = route['duration']  # 直接使用分钟数

            # 如果时间大于60分钟，显示小时和分钟
            if duration_minutes >= 60:
                hours = int(duration_minutes // 60)
                minutes = int(duration_minutes % 60)
                if minutes > 0:
                    duration = f"{hours}小时{minutes}分钟"
                else:
                    duration = f"{hours}小时"
            else:
                duration = f"{duration_minutes:.0f}分钟"

            print(f"📊 导航状态: 距离={distance}, 时间={duration} (原始={route['duration']}分钟)")

        return {
            'is_navigating': self.is_navigating,
            'current_location': self.current_location,
            'destination': self.destination,
            'distance': distance,
            'duration': duration,
            'has_route': self.route_data is not None,
            'map_available': self.map_html_path is not None and os.path.exists(self.map_html_path)
        }

    def cleanup(self):
        """清理临时文件"""
        try:
            if self.map_html_path and os.path.exists(self.map_html_path):
                os.unlink(self.map_html_path)
                self.map_html_path = None
            print("🗑️ 导航模块临时文件已清理")
        except Exception as e:
            print(f"❌ 清理临时文件失败: {e}")