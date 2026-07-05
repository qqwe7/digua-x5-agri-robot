#include "uart_driver.h"

uint8_t uart1_rx_dma_buffer[BUFFER_SIZE];
uint8_t uart1_ring_buffer_pool[BUFFER_SIZE];
struct rt_ringbuffer uart1_ring_buffer;
uint8_t uart1_data_buffer[BUFFER_SIZE];

uint8_t uart2_rx_dma_buffer[BUFFER_SIZE];
uint8_t uart2_ring_buffer_pool[BUFFER_SIZE];
struct rt_ringbuffer uart2_ring_buffer;
uint8_t uart2_data_buffer[BUFFER_SIZE];

uint8_t uart3_rx_dma_buffer[BUFFER_SIZE];
uint8_t uart3_ring_buffer_pool[BUFFER_SIZE];
struct rt_ringbuffer uart3_ring_buffer;
uint8_t uart3_data_buffer[BUFFER_SIZE];

uint8_t uart6_rx_dma_buffer[BUFFER_SIZE];
uint8_t uart6_ring_buffer_pool[BUFFER_SIZE];
struct rt_ringbuffer uart6_ring_buffer;
uint8_t uart6_data_buffer[BUFFER_SIZE];

uint8_t uart_rx_dma_buffer[BUFFER_SIZE];
uint8_t ring_buffer_input[BUFFER_SIZE];
struct rt_ringbuffer ring_buffer;
uint8_t uart_data_buffer[BUFFER_SIZE];

int my_printf(UART_HandleTypeDef *huart, const char *format, ...);

static void UartDriver_ClearRxError(UART_HandleTypeDef *huart)
{
    if (huart == NULL)
    {
        return;
    }

    __HAL_UART_CLEAR_PEFLAG(huart);
    __HAL_UART_CLEAR_FEFLAG(huart);
    __HAL_UART_CLEAR_NEFLAG(huart);
    __HAL_UART_CLEAR_OREFLAG(huart);
    __HAL_UART_CLEAR_IDLEFLAG(huart);
    huart->ErrorCode = HAL_UART_ERROR_NONE;
}

static void UartDriver_RestartRxDma(UART_HandleTypeDef *huart, DMA_HandleTypeDef *hdma, uint8_t *buffer)
{
    if ((huart == NULL) || (hdma == NULL) || (buffer == NULL))
    {
        return;
    }

    HAL_UART_DMAStop(huart);
    UartDriver_ClearRxError(huart);
    memset(buffer, 0, BUFFER_SIZE);

    if (HAL_UARTEx_ReceiveToIdle_DMA(huart, buffer, BUFFER_SIZE) == HAL_OK)
    {
        __HAL_DMA_DISABLE_IT(hdma, DMA_IT_HT);
    }
}

static void UartDriver_RestartRxByHandle(UART_HandleTypeDef *huart)
{
    if (huart->Instance == USART1)
    {
        UartDriver_RestartRxDma(huart, &hdma_usart1_rx, uart1_rx_dma_buffer);
    }
    else if (huart->Instance == USART2)
    {
        UartDriver_RestartRxDma(huart, &hdma_usart2_rx, uart2_rx_dma_buffer);
    }
    else if (huart->Instance == USART3)
    {
        UartDriver_RestartRxDma(huart, &hdma_usart3_rx, uart3_rx_dma_buffer);
    }
    else if (huart->Instance == USART6)
    {
        UartDriver_RestartRxDma(huart, &hdma_usart6_rx, uart6_rx_dma_buffer);
    }
}

void HAL_UARTEx_RxEventCallback(UART_HandleTypeDef *huart, uint16_t Size)
{
    if (huart->Instance == USART1)
    {
        if (Size > 0U)
        {
            rt_ringbuffer_put(&uart1_ring_buffer, uart1_rx_dma_buffer, Size);
        }
        UartDriver_RestartRxDma(&huart1, &hdma_usart1_rx, uart1_rx_dma_buffer);
    }
    else if (huart->Instance == USART2)
    {
        if (Size > 0U)
        {
            rt_ringbuffer_put(&uart2_ring_buffer, uart2_rx_dma_buffer, Size);
        }
        UartDriver_RestartRxDma(&huart2, &hdma_usart2_rx, uart2_rx_dma_buffer);
    }
    else if (huart->Instance == USART3)
    {
        if (Size > 0U)
        {
            rt_ringbuffer_put(&uart3_ring_buffer, uart3_rx_dma_buffer, Size);
        }
        UartDriver_RestartRxDma(&huart3, &hdma_usart3_rx, uart3_rx_dma_buffer);
    }
    else if (huart->Instance == USART6)
    {
        if (Size > 0U)
        {
            rt_ringbuffer_put(&uart6_ring_buffer, uart6_rx_dma_buffer, Size);
        }
        UartDriver_RestartRxDma(&huart6, &hdma_usart6_rx, uart6_rx_dma_buffer);
    }
}

void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
    UartDriver_RestartRxByHandle(huart);
}

void UartDriver_ServiceRxHealth(void)
{
    if ((huart1.ErrorCode != HAL_UART_ERROR_NONE) || (huart1.RxState != HAL_UART_STATE_BUSY_RX))
    {
        UartDriver_RestartRxDma(&huart1, &hdma_usart1_rx, uart1_rx_dma_buffer);
    }

    if ((huart2.ErrorCode != HAL_UART_ERROR_NONE) || (huart2.RxState != HAL_UART_STATE_BUSY_RX))
    {
        UartDriver_RestartRxDma(&huart2, &hdma_usart2_rx, uart2_rx_dma_buffer);
    }

    if ((huart3.ErrorCode != HAL_UART_ERROR_NONE) || (huart3.RxState != HAL_UART_STATE_BUSY_RX))
    {
        UartDriver_RestartRxDma(&huart3, &hdma_usart3_rx, uart3_rx_dma_buffer);
    }

    if ((huart6.ErrorCode != HAL_UART_ERROR_NONE) || (huart6.RxState != HAL_UART_STATE_BUSY_RX))
    {
        UartDriver_RestartRxDma(&huart6, &hdma_usart6_rx, uart6_rx_dma_buffer);
    }
}
