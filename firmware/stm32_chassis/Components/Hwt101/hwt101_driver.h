#ifndef __HWT101_DRIVER_H__
#define __HWT101_DRIVER_H__

#ifdef __cplusplus
extern "C" {
#endif

#include "main.h"
#include "usart.h"
#include <stdarg.h>

extern int my_printf(UART_HandleTypeDef *huart, const char *format, ...);

typedef enum {
    HWT101_STATE_IDLE = 0,
    HWT101_STATE_RECEIVING,
    HWT101_STATE_DATA_READY,
    HWT101_STATE_ERROR
} HWT101_State_t;

typedef struct {
    UART_HandleTypeDef *huart;
    uint32_t timeout_ms;
} HWT101_HW_t;

typedef struct {
    float roll;
    float pitch;
    float yaw;
    float gyro_z_raw;
    float gyro_z;
    uint16_t version;
    uint32_t timestamp;
    uint8_t data_valid;
} HWT101_Data_t;

typedef struct {
    HWT101_HW_t hw;
    HWT101_Data_t data;
    HWT101_State_t state;
    uint8_t enable;
    uint8_t rx_buffer[32];
    uint8_t rx_index;
} HWT101_t;

#define HWT101_PACKET_SIZE          11
#define HWT101_TIMEOUT_MS           1000
#define HWT101_BUFFER_SIZE          32

#define HWT101_HEADER               0x55
#define HWT101_TYPE_GYRO            0x52
#define HWT101_TYPE_ANGLE           0x53

#define HWT101_CMD_HEADER1          0xFF
#define HWT101_CMD_HEADER2          0xAA
#define HWT101_UNLOCK_CODE1         0x69
#define HWT101_UNLOCK_CODE2         0x88
#define HWT101_UNLOCK_CODE3         0xB5

#define HWT101_REG_SAVE             0x00
#define HWT101_REG_RRATE            0x03
#define HWT101_REG_BAUD             0x04
#define HWT101_REG_CALIYAW          0x76
#define HWT101_REG_MANUALCALI       0xA6
#define HWT101_REG_NOAUTOCALI       0xA7

int8_t HWT101_Create(HWT101_t *hwt, UART_HandleTypeDef *huart, uint32_t timeout_ms);
int8_t HWT101_ProcessBuffer(HWT101_t *hwt, uint8_t *buffer, uint16_t length);
float HWT101_GetGyroZ(HWT101_t *hwt);
float HWT101_GetYaw(HWT101_t *hwt);
HWT101_Data_t *HWT101_GetData(HWT101_t *hwt);
int8_t HWT101_SetBaudRate(HWT101_t *hwt, uint8_t baud_code);
int8_t HWT101_SetOutputRate(HWT101_t *hwt, uint8_t rate_code);
int8_t HWT101_StartManualCalibration(HWT101_t *hwt);
int8_t HWT101_StopManualCalibration(HWT101_t *hwt);
int8_t HWT101_ResetYaw(HWT101_t *hwt);
int8_t HWT101_SaveConfig(HWT101_t *hwt);
HWT101_State_t HWT101_GetState(HWT101_t *hwt);
int8_t HWT101_Enable(HWT101_t *hwt, uint8_t enable);

#ifdef __cplusplus
}
#endif

#endif
