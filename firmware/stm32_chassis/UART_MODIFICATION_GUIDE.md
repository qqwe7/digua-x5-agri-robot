# 串口缓冲池独立分配方案

## 📋 改动内容总结

### 1. 文件修改列表

#### ✅ uart_driver.c
- 为UART1添加独立的缓冲结构：
  - `uart1_rx_dma_buffer[BUFFER_SIZE]` - DMA接收缓冲
  - `uart1_ring_buffer_pool[BUFFER_SIZE]` - 环形缓冲池
  - `uart1_ring_buffer` - 环形缓冲结构体
  - `uart1_data_buffer[BUFFER_SIZE]` - 数据处理缓冲

- 为UART2添加独立的缓冲结构：
  - `uart2_rx_dma_buffer[BUFFER_SIZE]` - DMA接收缓冲
  - `uart2_ring_buffer_pool[BUFFER_SIZE]` - 环形缓冲池
  - `uart2_ring_buffer` - 环形缓冲结构体
  - `uart2_data_buffer[BUFFER_SIZE]` - 数据处理缓冲

- 修改 `HAL_UARTEx_RxEventCallback()` 回调函数：
  - 现在可以区分USART1和USART2
  - 每个串口处理自己独立的缓冲池

- 保留向后兼容接口：
  - 原有的 `uart_rx_dma_buffer` 等变量仍然存在
  - 旧代码无需修改

#### ✅ uart_driver.h
- 添加UART2的DMA变量声明：`extern DMA_HandleTypeDef hdma_usart2_rx;`

#### ✅ uart_app.h
- 新增接口：
  - `Uart1_Init()` - 初始化UART1
  - `Uart1_Task()` - 处理UART1数据
  - `Uart2_Init()` - 初始化UART2
  - `Uart2_Task()` - 处理UART2数据
  - 保留原有接口用于向后兼容

#### ✅ uart_app.c
- 为UART1实现独立的初始化和处理
- 为UART2实现独立的初始化和处理
- 原有接口自动调用UART1相关函数（向后兼容）

---

## 🔧 后续配置步骤

### 第1步：配置UART2的DMA（如果需要）

如果你要使用UART2接收，需要在**CubeMX**中配置DMA：

1. 打开`.ioc`文件
2. 找到USART2配置
3. 在"DMA Settings"中添加RX DMA：
   - DMA: `DMA1_Stream5` 或 `DMA1_Stream6`
   - Channel: `Channel 4`
   - Mode: `Circular` 或 `Normal`

4. 重新生成代码

**或者** 改成中断接收（不用DMA）

---

### 第2步：更新main.c中的初始化

在 `main()` 函数中：

```c
/* 原有代码保持不变 */
Uart_Init();

/* 如果需要同时使用UART1和UART2 */
Uart1_Init();
Uart2_Init();
```

---

### 第3步：更新Scheduler中的任务

在 `scheduler.c` 的 `Scheduler_Run()` 中：

```c
/* 原有代码 */
Uart_Task();

/* 新增 */
Uart1_Task();   // 处理UART1接收的数据
Uart2_Task();   // 处理UART2接收的数据
```

---

## 📊 使用示例

### 仅使用UART1（现状，无需改动）
```c
Uart_Init();      // 初始化UART1

// 在scheduler中
Uart_Task();      // 处理UART1数据
```

### 使用UART1和UART2
```c
Uart1_Init();     // 初始化UART1
Uart2_Init();     // 初始化UART2

// 在scheduler中
Uart1_Task();     // 处理UART1数据
Uart2_Task();     // 处理UART2数据
```

### 在UART1_Task中处理数据
```c
void Uart1_Task(void)
{
  uint16_t uart_data_len = rt_ringbuffer_data_len(&uart1_ring_buffer);
  if(uart_data_len > 0)
  {
    rt_ringbuffer_get(&uart1_ring_buffer, uart1_data_buffer, uart_data_len);
    uart1_data_buffer[uart_data_len] = '\0';
    
    // ===== 在这里处理接收到的数据 =====
    // 例如：解析命令、更新参数等
    my_printf(&huart1, "UART1 Received: %s\r\n", uart1_data_buffer);
    
    memset(uart1_data_buffer, 0, uart_data_len);
  }
}
```

---

## ⚠️ 重要注意事项

1. **向后兼容**：原有代码无需修改，仍可使用 `Uart_Init()` 和 `Uart_Task()`

2. **缓冲池大小**：都是128字节，可在 `uart_driver.h` 中修改 `BUFFER_SIZE`

3. **UART2 DMA**：需要在CubeMX中配置，否则 `hdma_usart2_rx` 会未定义

4. **数据处理**：在 `Uart1_Task()` 和 `Uart2_Task()` 中实现具体的数据处理逻辑

---

## 📝 架构图

```
UART1硬件
   ↓
DMA → uart1_rx_dma_buffer[128]
   ↓
rt_ringbuffer_put() → uart1_ring_buffer
   ↓
Uart1_Task() → rt_ringbuffer_get() → uart1_data_buffer
   ↓
用户处理数据


UART2硬件
   ↓
DMA → uart2_rx_dma_buffer[128]
   ↓
rt_ringbuffer_put() → uart2_ring_buffer
   ↓
Uart2_Task() → rt_ringbuffer_get() → uart2_data_buffer
   ↓
用户处理数据
```

---

## ✨ 优点

✅ 每个串口独立缓冲，互不干扰
✅ 支持同时使用多个串口
✅ 向后兼容，无需修改现有代码
✅ 易于扩展（添加UART3、UART4等）
✅ 数据隔离，便于调试

