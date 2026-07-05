# 4G 云控最小方案

这套方案的链路是：

1. 手机网页打开云端控制页
2. 网页把控制命令发到云端 HTTP 服务
3. 云端 HTTP 服务把命令转发到同机 TCP 桥接服务
4. `M100P` 通过 4G 透明传输连到这个 TCP 桥接端口
5. `STM32 UART3` 收到文本命令后执行

## 为什么不是网页直接连 4G 模块

手机浏览器不能直接发原始 TCP 到 4G 模块，所以需要一个很薄的云端转发层。

## 目录

- [server.py](D:/jichuang/Car_Xifeng_F4(uart)/cloud_control/server.py): 无第三方依赖的桥接服务
- [index.html](D:/jichuang/Car_Xifeng_F4(uart)/cloud_control/static/index.html): 手机网页控制台
- [local_control.py](D:/jichuang/Car_Xifeng_F4(uart)/cloud_control/local_control.py): 本地电脑测试启动器
- [local_test_config.json](D:/jichuang/Car_Xifeng_F4(uart)/cloud_control/local_test_config.json): 本地测试配置
- [start_local_control.bat](D:/jichuang/Car_Xifeng_F4(uart)/cloud_control/start_local_control.bat): 双击启动本地网页控车
- [start_cloud_server.bat](D:/jichuang/Car_Xifeng_F4(uart)/cloud_control/start_cloud_server.bat): 双击启动云端服务器

## 电脑本地先测

如果先不用 4G，只想在当前电脑上用网页控制已经插着 USB 的 STM32：

1. 确认 STM32 串口是 `COM11`
2. 双击 [start_local_control.bat](D:/jichuang/Car_Xifeng_F4(uart)/cloud_control/start_local_control.bat)
3. 浏览器会自动打开本地网页
4. 直接点网页上的 `前进 / 后退 / 左转 / 右转 / 停止`

本地模式走的是：

```text
网页 -> 本地 HTTP 服务 -> 本地 TCP 桥 -> COM11(UART1) -> STM32
```

如果你的串口号不是 `COM11`，改 [local_test_config.json](D:/jichuang/Car_Xifeng_F4(uart)/cloud_control/local_test_config.json) 里的 `serial_port` 即可。

## 运行服务

在有公网 IP 的 Windows / Linux 主机上运行：

```bash
python server.py --bind 0.0.0.0 --http-port 8080 --tcp-port 9000 --token yourtoken
```

运行后会同时打开两个端口：

- `8080`: 手机网页访问入口
- `9000`: 给 `M100P` 透明 TCP 连接的桥接端口

## 模块侧建议

把 `M100P` 配成：

- 4G 上网正常
- 透明传输模式
- TCP Client
- 目标服务器 = 云主机公网 IP
- 目标端口 = `9000`

模块连上后，云端会把它当作当前在线小车。

## 手机侧使用

手机浏览器打开：

```text
http://你的云主机公网IP:8080/
```

输入 token 后，就可以直接发这些命令：

- `carfwd 10`
- `carback 10`
- `carleft 10`
- `carright 10`
- `carstop`
- `status`

## 当前车端协议

STM32 `UART3` 已支持这些文本指令：

- `ping`
- `status`
- `canmode [speed|current|pos]`
- `canrpm <id> <rpm>`
- `can4 <r1> <r2> <r3> <r4>`
- `carfwd <rpm>`
- `carback <rpm>`
- `carleft <rpm>`
- `carright <rpm>`
- `carstop`
- `canstop <id>`
- `canstopall`
- `canrx`

返回格式示例：

```text
OK pong
OK status tick=12345 can=1 imu=1 yaw_rel=0.00
OK carfwd 12.00
ERR usage: carfwd <rpm>
```

## 安全建议

- 现在 STM32 侧已经加了 `UART3` 远控超时停车，远控指令超过约 `1.5s` 不续发会自动停
- 正式上车前，建议把速度先限制在 `10~20 rpm`
- 云主机建议只开放必要端口，并改掉默认 token

## 下一步可以继续做

- 给云端加账号登录和多车管理
- 给页面加长按连发
- 给 STM32 加状态主动上报
- 根据你的 `M100P` 型号补具体 AT 配置脚本
