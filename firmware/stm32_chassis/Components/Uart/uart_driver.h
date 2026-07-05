#ifndef __UART_DRIVER_H__
#define __UART_DRIVER_H__

#include "MyDefine.h"

#define BUFFER_SIZE 128

extern DMA_HandleTypeDef hdma_usart1_rx;
extern DMA_HandleTypeDef hdma_usart2_rx;
extern DMA_HandleTypeDef hdma_usart3_rx;
extern DMA_HandleTypeDef hdma_usart6_rx;

int my_printf(UART_HandleTypeDef *huart, const char *format, ...);
void HAL_UARTEx_RxEventCallback(UART_HandleTypeDef *huart, uint16_t Size);
void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart);
void UartDriver_ServiceRxHealth(void);

#endif
