# WebSocket 事件契约

## 1. 连接地址

`GET /ws/state`

## 2. 事件类型

### `state.update`

用于推送统一状态对象。

### `command.result`

用于推送最近命令执行结果。

### `fault.update`

用于推送故障变化。

### `log.append`

用于推送新增日志。

## 3. 事件封装格式

```json
{
  "event": "state.update",
  "timestamp": "2026-04-21T12:00:00+08:00",
  "payload": {}
}
```
