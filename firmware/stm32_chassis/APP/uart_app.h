#ifndef __UART_APP_H__
#define __UART_APP_H__

#include "MyDefine.h"

void Uart_Init(void);
void Uart1_Init(void);
void Uart2_Init(void);
void Uart6_Init(void);

void Uart_Task(void);
void Uart1_Task(void);
void Uart2_Task(void);
void Uart6_Task(void);

#endif
