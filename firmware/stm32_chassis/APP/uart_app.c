#include "uart_app.h"
#include "../Components/Hwt101/hwt101_driver.h"
#include "dht11_app.h"
#include "light_app.h"
#include "can_motor_app.h"

extern uint8_t uart1_rx_dma_buffer[BUFFER_SIZE];
extern uint8_t uart1_ring_buffer_pool[BUFFER_SIZE];
extern struct rt_ringbuffer uart1_ring_buffer;
extern uint8_t uart1_data_buffer[BUFFER_SIZE];

extern uint8_t uart2_rx_dma_buffer[BUFFER_SIZE];
extern uint8_t uart2_ring_buffer_pool[BUFFER_SIZE];
extern struct rt_ringbuffer uart2_ring_buffer;
extern uint8_t uart2_data_buffer[BUFFER_SIZE];

extern uint8_t uart3_rx_dma_buffer[BUFFER_SIZE];
extern uint8_t uart3_ring_buffer_pool[BUFFER_SIZE];
extern struct rt_ringbuffer uart3_ring_buffer;
extern uint8_t uart3_data_buffer[BUFFER_SIZE];

extern uint8_t uart6_rx_dma_buffer[BUFFER_SIZE];
extern uint8_t uart6_ring_buffer_pool[BUFFER_SIZE];
extern struct rt_ringbuffer uart6_ring_buffer;
extern uint8_t uart6_data_buffer[BUFFER_SIZE];

#define DEBUG_UART_HEARTBEAT_MS 1000U
#define M100P_UART_BAUD 115200U
#define M100P_RX_PRINT_MAX 64U
#define M100P_REMOTE_CMD_TIMEOUT_MS 1500U
#define AUTO_BACKGROUND_LOGS 0U
#define HWT101_REPORT_PERIOD_MS 200U
#define HWT101_STALE_TIMEOUT_MS 1000U
#define HWT101_WAIT_REPORT_MS 3000U
#define DHT11_SAMPLE_PERIOD_MS 2000U
#define DHT11_STALE_TIMEOUT_MS 5000U
#define DHT11_FAIL_REPORT_MS 3000U
#define LIGHT_SAMPLE_PERIOD_MS 1000U
#define LIGHT_STALE_TIMEOUT_MS 3000U
#define HWT101_VOFA_MODE 0U
#define PROTO_FRAME_HEADER0 0xAAU
#define PROTO_FRAME_HEADER1 0x55U
#define PROTO_VERSION       0x01U
#define PROTO_MSG_STATUS    0x01U
#define PROTO_MSG_CONTROL   0x02U
#define PROTO_MSG_IMU_ZERO  0x03U
#define PROTO_REQ_STATUS    0x01U
#define PROTO_STATUS_LEN    20U
#define PROTO_CONTROL_LEN   10U
#define PROTO_IMU_ZERO_LEN  4U
#define UART6_CONTROL_TIMEOUT_MS 500U
#define UART6_RX_DEBUG_PRINT 1U

static HWT101_t g_hwt101;
static DHT11_t g_dht11;
static Light_t g_light;
static uint8_t g_hwt101_ready = 0;
static uint8_t g_dht11_ready = 0;
static uint8_t g_light_ready = 0;
static uint8_t g_hwt101_first_frame_logged = 0;
static uint32_t g_uart2_raw_frame_count = 0;
static float g_yaw_zero = 0.0f;
static uint8_t g_yaw_zero_valid = 0U;
static uint8_t g_proto_seq = 0U;
static uint8_t g_m100p_motion_active = 0U;
static uint32_t g_m100p_last_motion_tick = 0U;
static uint8_t g_uart6_motion_active = 0U;
static uint8_t g_uart6_chassis_mode = 0U;
static uint8_t g_uart6_speed_mode_set = 0U;
static uint32_t g_uart6_last_control_tick = 0U;

static void Hwt101_AppInit(void);
static void Dht11_AppInit(void);
static void Light_AppInit(void);
static void Hwt101_ProcessRxFrame(const uint8_t *buffer, uint16_t length);
static void Hwt101_ReportData(void);
static void Dht11_Task(void);
static void Light_Task(void);
static void Uart3_InternalInit(void);
static void Uart3_InternalTask(void);
static void M100P_SendAtLine(const char *line);
static void DebugUart_HandleCommand(void);
static void DebugUart_PrintHexFrame(const char *prefix, const uint8_t *buffer, uint16_t length);
static float Hwt101_NormalizeAngle(float angle_deg);
static void Hwt101_CaptureZero(float yaw_raw, const char *reason);
static uint16_t Proto_Crc16IBM(const uint8_t *data, uint16_t length);
static void Proto_WriteU16LE(uint8_t *dst, uint16_t value);
static void Proto_WriteU32LE(uint8_t *dst, uint32_t value);
static void Proto_WriteI16LE(uint8_t *dst, int16_t value);
static uint16_t Proto_ReadU16LE(const uint8_t *src);
static int16_t Proto_ReadI16LE(const uint8_t *src);
static uint8_t Hwt101_IsOnline(const HWT101_Data_t *data, uint32_t now_tick);
static void Uart6_SendStatusFrame(void);
static void Uart6_HandleRequest(void);
static uint8_t Uart6_TryHandleProtoFrame(const uint8_t *buffer, uint16_t length);
static void Uart6_HandleControlFrame(const uint8_t *payload, uint8_t payload_len);
static void Uart6_HandleImuZeroFrame(const uint8_t *payload, uint8_t payload_len);
static void Uart6_CheckControlTimeout(void);
static uint16_t Uart_ReadFrame(struct rt_ringbuffer *ring, uint8_t *buffer);
static uint16_t Uart_TrimLineEndings(uint8_t *buffer, uint16_t length);
static uint8_t Dht11_IsOnline(const DHT11_Data_t *data, uint32_t now_tick);
static uint8_t Light_IsOnline(const Light_Data_t *data, uint32_t now_tick);
static char *DebugUart_SkipSpaces(char *text);
static uint8_t DebugUart_ParseNextFloat(char **cursor, float *value);
static uint8_t DebugUart_ParseCanMode(char *args, uint8_t *mode, const char **mode_name);
static uint8_t DebugUart_ParseSingleRpmArg(char *args, float *rpm);
static void M100P_HandleRemoteCommand(void);
static void M100P_SendReply(const char *format, ...);
static void M100P_SendRemoteHelp(void);
static void M100P_SendRemoteStatus(void);
static void M100P_MarkMotionAlive(uint8_t active);
static void M100P_CheckMotionTimeout(void);
static void Uart_StartRxDma(
  struct rt_ringbuffer *ring,
  uint8_t *pool,
  UART_HandleTypeDef *uart,
  uint8_t *dma_buffer,
  DMA_HandleTypeDef *dma);
static void CanMotor_PrintLastRx(UART_HandleTypeDef *reply_uart);

static void DebugUart_SendStartupBanner(void)
{
#if !HWT101_VOFA_MODE
  my_printf(
    &huart1,
    "\r\n[IMU PLAN]\r\n"
    "UART1: debug / host uplink\r\n"
    "UART2: HWT101 IMU @ 9600\r\n"
    "UART3: M100P 4G module @ 115200\r\n"
    "wire: M100P TX->PB11 RX, M100P RX->PB10 TX, GND->GND\r\n"
    "wire: HWT101 TX->PA3, RX->PA2, GND->GND\r\n"
    "wire: CAN1 PB9->TXD, PB8->RXD, transceiver->CANH/CANL\r\n"
    "DHT11: DATA->PE2(KEY3), VCC->3V3/5V, GND->GND\r\n"
    "LIGHT: AO->PA0, VCC->3V3, GND->GND\r\n"
    "project fields: yaw_raw, yaw_zero, yaw_rel, gyro_z\r\n");
#endif
}

static void DebugUart_Heartbeat(void)
{
#if !HWT101_VOFA_MODE && AUTO_BACKGROUND_LOGS
  static uint32_t last_heartbeat_tick = 0;
  uint32_t now_tick = HAL_GetTick();

  if ((now_tick - last_heartbeat_tick) >= DEBUG_UART_HEARTBEAT_MS)
  {
    last_heartbeat_tick = now_tick;
    my_printf(&huart1, "[UART1] alive %lu ms\r\n", now_tick);
  }
#endif
}

static void Hwt101_AppInit(void)
{
  if (HWT101_Create(&g_hwt101, &huart2, HWT101_TIMEOUT_MS) == 0)
  {
    g_hwt101_ready = 1;
    g_hwt101_first_frame_logged = 0;
    g_uart2_raw_frame_count = 0;
#if !HWT101_VOFA_MODE
    my_printf(&huart1, "[HWT101] parser ready on UART2 @ %lu baud\r\n", huart2.Init.BaudRate);
    my_printf(&huart1, "[HWT101] commands: help, zero, hwzero, status, dht, light, send6, at, ati, csq, m100p <cmd>, canmode, canrpm, can4, carfwd, carback, carleft, carright, carstop, canstop, canstopall, canrx\r\n");
#endif
  }
  else
  {
    g_hwt101_ready = 0;
#if !HWT101_VOFA_MODE
    my_printf(&huart1, "[HWT101] init failed\r\n");
#endif
  }
}

static void M100P_SendAtLine(const char *line)
{
  if ((line == NULL) || (line[0] == '\0'))
  {
    return;
  }

  HAL_UART_Transmit(&huart3, (uint8_t *)line, (uint16_t)strlen(line), 200);
  HAL_UART_Transmit(&huart3, (uint8_t *)"\r\n", 2U, 200);
#if !HWT101_VOFA_MODE
  my_printf(&huart1, "[M100P TX] %s\r\n", line);
#endif
}

static void Dht11_AppInit(void)
{
  if (DHT11_Create(&g_dht11, DHT11_GPIO_Port, DHT11_Pin) == 0)
  {
    g_dht11_ready = 1U;
#if !HWT101_VOFA_MODE
    my_printf(&huart1, "[DHT11] ready on PE2(KEY3), sample period=%lu ms\r\n", DHT11_SAMPLE_PERIOD_MS);
#endif
  }
  else
  {
    g_dht11_ready = 0U;
#if !HWT101_VOFA_MODE
    my_printf(&huart1, "[DHT11] init failed\r\n");
#endif
  }
}

static void Light_AppInit(void)
{
  if (Light_Create(&g_light) == 0)
  {
    g_light_ready = 1U;
#if !HWT101_VOFA_MODE
    my_printf(&huart1, "[LIGHT] ready on PA0(ADC1_IN0), sample period=%lu ms\r\n", LIGHT_SAMPLE_PERIOD_MS);
#endif
  }
  else
  {
    g_light_ready = 0U;
#if !HWT101_VOFA_MODE
    my_printf(&huart1, "[LIGHT] init failed\r\n");
#endif
  }
}

static void Uart3_InternalInit(void)
{
  Uart_StartRxDma(
    &uart3_ring_buffer,
    uart3_ring_buffer_pool,
    &huart3,
    uart3_rx_dma_buffer,
    &hdma_usart3_rx);
#if !HWT101_VOFA_MODE
  my_printf(&huart1, "[M100P] UART3 ready @ %u baud\r\n", M100P_UART_BAUD);
#endif
}

static void DebugUart_PrintHexFrame(const char *prefix, const uint8_t *buffer, uint16_t length)
{
#if !HWT101_VOFA_MODE
  uint16_t i;
  uint16_t print_len = length;

  if (print_len > 32U)
  {
    print_len = 32U;
  }

  my_printf(&huart1, "%s %uB:", prefix, length);
  for (i = 0; i < print_len; i++)
  {
    my_printf(&huart1, " %02X", buffer[i]);
  }

  if (length > print_len)
  {
    my_printf(&huart1, " ...");
  }

  my_printf(&huart1, "\r\n");
#else
  (void)prefix;
  (void)buffer;
  (void)length;
#endif
}

static float Hwt101_NormalizeAngle(float angle_deg)
{
  while (angle_deg > 180.0f)
  {
    angle_deg -= 360.0f;
  }

  while (angle_deg < -180.0f)
  {
    angle_deg += 360.0f;
  }

  return angle_deg;
}

static void Hwt101_CaptureZero(float yaw_raw, const char *reason)
{
  g_yaw_zero = yaw_raw;
  g_yaw_zero_valid = 1U;
#if !HWT101_VOFA_MODE
  my_printf(&huart1, "[HWT101] zero set by %s, yaw_zero=%.2f deg\r\n", reason, g_yaw_zero);
#else
  (void)reason;
#endif
}

static uint16_t Proto_Crc16IBM(const uint8_t *data, uint16_t length)
{
  uint16_t crc = 0xFFFFU;
  uint16_t i;
  uint8_t j;

  for (i = 0U; i < length; i++)
  {
    crc ^= data[i];
    for (j = 0U; j < 8U; j++)
    {
      if ((crc & 0x0001U) != 0U)
      {
        crc = (uint16_t)((crc >> 1U) ^ 0xA001U);
      }
      else
      {
        crc >>= 1U;
      }
    }
  }

  return crc;
}

static void Proto_WriteU16LE(uint8_t *dst, uint16_t value)
{
  dst[0] = (uint8_t)(value & 0xFFU);
  dst[1] = (uint8_t)((value >> 8U) & 0xFFU);
}

static void Proto_WriteU32LE(uint8_t *dst, uint32_t value)
{
  dst[0] = (uint8_t)(value & 0xFFU);
  dst[1] = (uint8_t)((value >> 8U) & 0xFFU);
  dst[2] = (uint8_t)((value >> 16U) & 0xFFU);
  dst[3] = (uint8_t)((value >> 24U) & 0xFFU);
}

static void Proto_WriteI16LE(uint8_t *dst, int16_t value)
{
  Proto_WriteU16LE(dst, (uint16_t)value);
}

static uint16_t Proto_ReadU16LE(const uint8_t *src)
{
  return (uint16_t)(((uint16_t)src[1] << 8U) | src[0]);
}

static int16_t Proto_ReadI16LE(const uint8_t *src)
{
  return (int16_t)Proto_ReadU16LE(src);
}

static uint8_t Hwt101_IsOnline(const HWT101_Data_t *data, uint32_t now_tick)
{
  if ((data == NULL) || !g_hwt101_ready)
  {
    return 0U;
  }

  return ((now_tick - data->timestamp) <= HWT101_STALE_TIMEOUT_MS) ? 1U : 0U;
}

static uint8_t Dht11_IsOnline(const DHT11_Data_t *data, uint32_t now_tick)
{
  if ((data == NULL) || !g_dht11_ready || (data->data_valid == 0U))
  {
    return 0U;
  }

  return ((now_tick - data->timestamp) <= DHT11_STALE_TIMEOUT_MS) ? 1U : 0U;
}

static uint8_t Light_IsOnline(const Light_Data_t *data, uint32_t now_tick)
{
  if ((data == NULL) || !g_light_ready || (data->data_valid == 0U))
  {
    return 0U;
  }

  return ((now_tick - data->timestamp) <= LIGHT_STALE_TIMEOUT_MS) ? 1U : 0U;
}

static void Uart6_SendStatusFrame(void)
{
  uint8_t frame[6U + PROTO_STATUS_LEN + 2U];
  uint8_t *payload = &frame[6];
  HWT101_Data_t *data = HWT101_GetData(&g_hwt101);
  uint32_t now_tick = HAL_GetTick();
  uint8_t imu_online = Hwt101_IsOnline(data, now_tick);
  float yaw_raw_f = (imu_online != 0U) ? data->yaw : 0.0f;
  float yaw_zero_f = g_yaw_zero_valid ? g_yaw_zero : 0.0f;
  float yaw_rel_f = g_yaw_zero_valid ? Hwt101_NormalizeAngle(yaw_raw_f - g_yaw_zero) : 0.0f;
  float gyro_z_f = (imu_online != 0U) ? data->gyro_z : 0.0f;
  CanMotor_ChassisFeedback_t motor_feedback;
  uint8_t motor_online = CanMotor_GetChassisFeedback(&motor_feedback);
  uint16_t crc;

  frame[0] = PROTO_FRAME_HEADER0;
  frame[1] = PROTO_FRAME_HEADER1;
  frame[2] = PROTO_VERSION;
  frame[3] = PROTO_MSG_STATUS;
  frame[4] = g_proto_seq++;
  frame[5] = PROTO_STATUS_LEN;

  Proto_WriteU32LE(&payload[0], now_tick);
  Proto_WriteI16LE(&payload[4], (int16_t)(yaw_raw_f * 100.0f));
  Proto_WriteI16LE(&payload[6], (int16_t)(yaw_zero_f * 100.0f));
  Proto_WriteI16LE(&payload[8], (int16_t)(yaw_rel_f * 100.0f));
  Proto_WriteI16LE(&payload[10], (int16_t)(gyro_z_f * 100.0f));
  Proto_WriteI16LE(&payload[12], motor_feedback.left_speed_mmps);
  Proto_WriteI16LE(&payload[14], motor_feedback.right_speed_mmps);
  payload[16] = imu_online;
  payload[17] = motor_online;
  payload[18] = g_uart6_chassis_mode;
  payload[19] = motor_feedback.fault_code;

  crc = Proto_Crc16IBM(&frame[2], (uint16_t)(4U + PROTO_STATUS_LEN));
  Proto_WriteU16LE(&frame[6U + PROTO_STATUS_LEN], crc);

  HAL_UART_Transmit(&huart6, frame, sizeof(frame), 100);

#if !HWT101_VOFA_MODE && AUTO_BACKGROUND_LOGS
  DebugUart_PrintHexFrame("[UART6 TX]", frame, sizeof(frame));
  my_printf(
    &huart1,
    "[UART6] sent 0x01 status seq=%u imu_online=%u yaw_rel=%.2f gyro_z=%.2f\r\n",
    frame[4],
    imu_online,
    yaw_rel_f,
    gyro_z_f);
#endif
}

static void Uart6_HandleRequest(void)
{
  uint16_t uart_data_len = Uart_ReadFrame(&uart6_ring_buffer, uart6_data_buffer);
  uint16_t i;

  if (uart_data_len == 0U)
  {
    return;
  }

#if UART6_RX_DEBUG_PRINT
  my_printf(&huart1, "[UART6 RX] len=%u:", uart_data_len);
  for (uint16_t j = 0U; j < uart_data_len; j++)
  {
    my_printf(&huart1, " %02X", uart6_data_buffer[j]);
  }
  my_printf(&huart1, "\r\n");
#endif

  if (Uart6_TryHandleProtoFrame(uart6_data_buffer, uart_data_len) != 0U)
  {
    memset(uart6_data_buffer, 0, uart_data_len + 1U);
    return;
  }

  for (i = 0U; i < uart_data_len; i++)
  {
    if (uart6_data_buffer[i] == PROTO_REQ_STATUS)
    {
      Uart6_SendStatusFrame();
      memset(uart6_data_buffer, 0, uart_data_len);
      return;
    }
  }

  uart_data_len = Uart_TrimLineEndings(uart6_data_buffer, uart_data_len);
  if ((uart_data_len == 2U) &&
      (uart6_data_buffer[0] == '0') &&
      (uart6_data_buffer[1] == '1'))
  {
    Uart6_SendStatusFrame();
  }
  else if ((uart_data_len == 4U) &&
           ((uart6_data_buffer[0] == '0') || (uart6_data_buffer[0] == 'O')) &&
           ((uart6_data_buffer[1] == 'x') || (uart6_data_buffer[1] == 'X')) &&
           (uart6_data_buffer[2] == '0') &&
           (uart6_data_buffer[3] == '1'))
  {
    Uart6_SendStatusFrame();
  }
#if !HWT101_VOFA_MODE && AUTO_BACKGROUND_LOGS
  else
  {
    my_printf(&huart1, "[UART6] unknown request len=%u\r\n", uart_data_len);
  }
#endif

  memset(uart6_data_buffer, 0, uart_data_len + 1U);
}

static uint8_t Uart6_TryHandleProtoFrame(const uint8_t *buffer, uint16_t length)
{
  uint16_t i;
  uint8_t handled = 0U;

  if (buffer == NULL)
  {
    return 0U;
  }

  i = 0U;
  while (i < length)
  {
    uint8_t payload_len;
    uint16_t frame_len;
    uint16_t rx_crc;
    uint16_t calc_crc;

    if ((uint16_t)(i + 8U) <= length &&
        (buffer[i] == PROTO_FRAME_HEADER0) &&
        (buffer[i + 1U] == PROTO_FRAME_HEADER1) &&
        (buffer[i + 2U] == PROTO_VERSION))
    {
      payload_len = buffer[i + 5U];
      frame_len = (uint16_t)(6U + payload_len + 2U);
      if ((uint16_t)(i + frame_len) > length)
      {
        break;
      }

      rx_crc = Proto_ReadU16LE(&buffer[i + 6U + payload_len]);
      calc_crc = Proto_Crc16IBM(&buffer[i + 2U], (uint16_t)(4U + payload_len));
      if (rx_crc != calc_crc)
      {
        i++;
        continue;
      }

      if ((buffer[i + 3U] == PROTO_MSG_CONTROL) && (payload_len == PROTO_CONTROL_LEN))
      {
        Uart6_HandleControlFrame(&buffer[i + 6U], payload_len);
        handled = 1U;
      }
      else if ((buffer[i + 3U] == PROTO_MSG_IMU_ZERO) && (payload_len == PROTO_IMU_ZERO_LEN))
      {
        Uart6_HandleImuZeroFrame(&buffer[i + 6U], payload_len);
        handled = 1U;
      }
      else if ((buffer[i + 3U] == PROTO_REQ_STATUS) && (payload_len == 0U))
      {
        Uart6_SendStatusFrame();
        handled = 1U;
      }
      else if ((buffer[i + 3U] == PROTO_MSG_STATUS) && (payload_len == PROTO_STATUS_LEN))
      {
        handled = 1U;
      }

      i = (uint16_t)(i + frame_len);
      continue;
    }

    if (buffer[i] == PROTO_REQ_STATUS)
    {
      Uart6_SendStatusFrame();
      handled = 1U;
    }

    i++;
  }

  return handled;
}

static void Uart6_HandleControlFrame(const uint8_t *payload, uint8_t payload_len)
{
  int16_t target_linear_mmps;
  int16_t target_angular_cdegps;
  int16_t target_yaw_cdeg;
  uint8_t control_mode;

  if ((payload == NULL) || (payload_len < PROTO_CONTROL_LEN))
  {
    return;
  }

  target_linear_mmps = Proto_ReadI16LE(&payload[0]);
  target_angular_cdegps = Proto_ReadI16LE(&payload[2]);
  target_yaw_cdeg = Proto_ReadI16LE(&payload[4]);
  control_mode = payload[6];
  (void)target_yaw_cdeg;

  if (g_uart6_speed_mode_set == 0U)
  {
    (void)CanMotor_SetModeAll(0x02U);
    g_uart6_speed_mode_set = 1U;
  }

  if (control_mode >= 3U)
  {
    (void)CanMotor_StopAll();
    g_uart6_motion_active = 0U;
    g_uart6_chassis_mode = 0U;
    return;
  }

  if (CanMotor_SetChassisVelocityMmps(target_linear_mmps, target_angular_cdegps) == HAL_OK)
  {
    g_uart6_last_control_tick = HAL_GetTick();
    g_uart6_motion_active = ((target_linear_mmps != 0) || (target_angular_cdegps != 0)) ? 1U : 0U;
    g_uart6_chassis_mode = (g_uart6_motion_active != 0U) ? 2U : 0U;
  }
}

static void Uart6_HandleImuZeroFrame(const uint8_t *payload, uint8_t payload_len)
{
  uint8_t zero_type;

  if ((payload == NULL) || (payload_len < PROTO_IMU_ZERO_LEN))
  {
    return;
  }

  zero_type = payload[0];
  if (zero_type == 0U)
  {
    if (g_hwt101_ready && g_hwt101.data.data_valid)
    {
      Hwt101_CaptureZero(g_hwt101.data.yaw, "uart6_soft_zero");
    }
  }
  else
  {
    if (g_hwt101_ready && (HWT101_ResetYaw(&g_hwt101) == 0))
    {
      g_yaw_zero = 0.0f;
      g_yaw_zero_valid = 1U;
    }
  }
}

static void Uart6_CheckControlTimeout(void)
{
  if ((g_uart6_motion_active != 0U) &&
      ((HAL_GetTick() - g_uart6_last_control_tick) >= UART6_CONTROL_TIMEOUT_MS))
  {
    (void)CanMotor_StopAll();
    g_uart6_motion_active = 0U;
    g_uart6_chassis_mode = 0U;
#if !HWT101_VOFA_MODE
    my_printf(&huart1, "[UART6] control timeout -> stop\r\n");
#endif
  }
}

static void Hwt101_ProcessRxFrame(const uint8_t *buffer, uint16_t length)
{
  if (!g_hwt101_ready || length == 0U)
  {
    return;
  }

  g_uart2_raw_frame_count++;
  if (g_uart2_raw_frame_count <= 5U)
  {
    DebugUart_PrintHexFrame("[UART2 RAW]", buffer, length);
  }

  HWT101_ProcessBuffer(&g_hwt101, (uint8_t *)buffer, length);

  if (g_hwt101.data.data_valid && !g_hwt101_first_frame_logged)
  {
    g_hwt101_first_frame_logged = 1;
    Hwt101_CaptureZero(g_hwt101.data.yaw, "first_frame");
#if !HWT101_VOFA_MODE
    my_printf(&huart1, "[HWT101] first valid frame at %lu ms\r\n", g_hwt101.data.timestamp);
#endif
  }
}

static void Hwt101_ReportData(void)
{
  static uint32_t last_report_tick = 0;
  static uint32_t last_wait_report_tick = 0;
  uint32_t now_tick = HAL_GetTick();
  HWT101_Data_t *data;

  if (!g_hwt101_ready)
  {
    return;
  }

  data = HWT101_GetData(&g_hwt101);

  if ((data != NULL) && ((now_tick - data->timestamp) <= HWT101_STALE_TIMEOUT_MS))
  {
    if ((now_tick - last_report_tick) >= HWT101_REPORT_PERIOD_MS)
    {
      float yaw_raw = data->yaw;
      float yaw_rel = g_yaw_zero_valid ? Hwt101_NormalizeAngle(yaw_raw - g_yaw_zero) : 0.0f;

      last_report_tick = now_tick;
#if HWT101_VOFA_MODE
      my_printf(&huart1, "imu:%.2f,%.2f\n", yaw_rel, data->gyro_z);
#elif AUTO_BACKGROUND_LOGS
      my_printf(
        &huart1,
        "[IMU] online=1 yaw_raw=%.2f deg yaw_zero=%.2f deg yaw_rel=%.2f deg gyro_z=%.2f dps ts=%lu\r\n",
        yaw_raw,
        g_yaw_zero,
        yaw_rel,
        data->gyro_z,
        data->timestamp);
#endif
    }
    return;
  }

  if ((now_tick - last_wait_report_tick) >= HWT101_WAIT_REPORT_MS)
  {
    last_wait_report_tick = now_tick;
#if !HWT101_VOFA_MODE && AUTO_BACKGROUND_LOGS
    my_printf(
      &huart1,
      "[IMU] online=0 waiting for valid data, check TX->PA3 RX->PA2 GND and baud=%lu\r\n",
      huart2.Init.BaudRate);
#endif
  }
}

static void Dht11_Task(void)
{
  static uint32_t last_sample_tick = 0U;
  static uint32_t last_fail_report_tick = 0U;
  uint32_t now_tick = HAL_GetTick();

  if (!g_dht11_ready)
  {
    return;
  }

  if ((now_tick - last_sample_tick) < DHT11_SAMPLE_PERIOD_MS)
  {
    return;
  }

  last_sample_tick = now_tick;
  if (DHT11_Read(&g_dht11) == 0)
  {
#if !HWT101_VOFA_MODE && AUTO_BACKGROUND_LOGS
    DHT11_Data_t *data = DHT11_GetData(&g_dht11);
    my_printf(
      &huart1,
      "[DHT11] online=1 humidity=%.1f %% temperature=%.1f C ts=%lu\r\n",
      data->humidity,
      data->temperature,
      data->timestamp);
#endif
  }
  else if ((now_tick - last_fail_report_tick) >= DHT11_FAIL_REPORT_MS)
  {
    last_fail_report_tick = now_tick;
#if !HWT101_VOFA_MODE && AUTO_BACKGROUND_LOGS
    my_printf(
      &huart1,
      "[DHT11] read failed err=%d, check DATA->PE2(KEY3) VCC GND\r\n",
      g_dht11.last_error);
#endif
  }
}

static void Light_Task(void)
{
  static uint32_t last_sample_tick = 0U;
  uint32_t now_tick = HAL_GetTick();

  if (!g_light_ready)
  {
    return;
  }

  if ((now_tick - last_sample_tick) < LIGHT_SAMPLE_PERIOD_MS)
  {
    return;
  }

  last_sample_tick = now_tick;
  if (Light_Read(&g_light) == 0)
  {
#if !HWT101_VOFA_MODE && AUTO_BACKGROUND_LOGS
    Light_Data_t *data = Light_GetData(&g_light);
    my_printf(
      &huart1,
      "[LIGHT] online=1 raw=%u level=%.1f %% ts=%lu\r\n",
      data->raw,
      data->level_percent,
      data->timestamp);
#endif
  }
}

static void Uart3_InternalTask(void)
{
  M100P_CheckMotionTimeout();
  M100P_HandleRemoteCommand();
}

static uint16_t Uart_TrimLineEndings(uint8_t *buffer, uint16_t length)
{
  while ((length > 0U) && ((buffer[length - 1U] == '\r') || (buffer[length - 1U] == '\n')))
  {
    buffer[length - 1U] = '\0';
    length--;
  }

  return length;
}

static char *DebugUart_SkipSpaces(char *text)
{
  while ((text != NULL) && ((*text == ' ') || (*text == '\t')))
  {
    text++;
  }

  return text;
}

static uint8_t DebugUart_ParseNextFloat(char **cursor, float *value)
{
  char *start;
  char *end_ptr;

  if ((cursor == NULL) || (*cursor == NULL) || (value == NULL))
  {
    return 0U;
  }

  start = DebugUart_SkipSpaces(*cursor);
  if ((start == NULL) || (*start == '\0'))
  {
    return 0U;
  }

  *value = strtof(start, &end_ptr);
  if (end_ptr == start)
  {
    return 0U;
  }

  *cursor = end_ptr;
  return 1U;
}

static uint8_t DebugUart_ParseCanMode(char *args, uint8_t *mode, const char **mode_name)
{
  char *mode_text = DebugUart_SkipSpaces(args);

  if ((mode == NULL) || (mode_name == NULL))
  {
    return 0U;
  }

  if ((mode_text == NULL) || (*mode_text == '\0') || (strcmp(mode_text, "speed") == 0) || (strcmp(mode_text, "2") == 0))
  {
    *mode = 0x02U;
    *mode_name = "speed";
    return 1U;
  }

  if ((strcmp(mode_text, "current") == 0) || (strcmp(mode_text, "1") == 0))
  {
    *mode = 0x01U;
    *mode_name = "current";
    return 1U;
  }

  if ((strcmp(mode_text, "pos") == 0) || (strcmp(mode_text, "position") == 0) || (strcmp(mode_text, "3") == 0))
  {
    *mode = 0x03U;
    *mode_name = "position";
    return 1U;
  }

  return 0U;
}

static uint8_t DebugUart_ParseSingleRpmArg(char *args, float *rpm)
{
  char *cursor = args;

  return DebugUart_ParseNextFloat(&cursor, rpm);
}

static void M100P_SendReply(const char *format, ...)
{
  char buffer[160];
  va_list args;
  int length;

  va_start(args, format);
  length = vsnprintf(buffer, sizeof(buffer), format, args);
  va_end(args);

  if (length < 0)
  {
    return;
  }

  if ((size_t)length >= sizeof(buffer))
  {
    length = (int)(sizeof(buffer) - 1U);
  }

  HAL_UART_Transmit(&huart3, (uint8_t *)buffer, (uint16_t)length, 200);
  HAL_UART_Transmit(&huart3, (uint8_t *)"\r\n", 2U, 200);
}

static void M100P_SendRemoteHelp(void)
{
  M100P_SendReply("OK cmds: ping, status, canmode [speed|current|pos], canrpm <id> <rpm>, can4 <r1> <r2> <r3> <r4>, carfwd <rpm>, carback <rpm>, carleft <rpm>, carright <rpm>, carstop, canstop <id>, canstopall, canrx");
}

static void M100P_SendRemoteStatus(void)
{
  uint32_t now_tick = HAL_GetTick();
  uint8_t imu_online = 0U;
  float yaw_rel = 0.0f;

  if (g_hwt101_ready && g_hwt101.data.data_valid)
  {
    imu_online = Hwt101_IsOnline(&g_hwt101.data, now_tick);
    if (g_yaw_zero_valid != 0U)
    {
      yaw_rel = Hwt101_NormalizeAngle(g_hwt101.data.yaw - g_yaw_zero);
    }
  }

  M100P_SendReply(
    "OK status tick=%lu can=%u imu=%u yaw_rel=%.2f",
    now_tick,
    CanMotor_IsReady(),
    imu_online,
    yaw_rel);
}

static void M100P_MarkMotionAlive(uint8_t active)
{
  g_m100p_last_motion_tick = HAL_GetTick();
  g_m100p_motion_active = active;
}

static void M100P_CheckMotionTimeout(void)
{
  if ((g_m100p_motion_active != 0U) &&
      ((HAL_GetTick() - g_m100p_last_motion_tick) >= M100P_REMOTE_CMD_TIMEOUT_MS))
  {
    (void)CanMotor_StopAll();
    g_m100p_motion_active = 0U;
#if !HWT101_VOFA_MODE
    my_printf(&huart1, "[M100P] remote motion timeout -> stop\r\n");
#endif
  }
}

static void M100P_HandleRemoteCommand(void)
{
  uint16_t uart_data_len = Uart_ReadFrame(&uart3_ring_buffer, uart3_data_buffer);

  if (uart_data_len == 0U)
  {
    return;
  }

  uart_data_len = Uart_TrimLineEndings(uart3_data_buffer, uart_data_len);
  if (uart_data_len == 0U)
  {
    return;
  }

#if !HWT101_VOFA_MODE
  my_printf(&huart1, "[M100P CMD] %s\r\n", uart3_data_buffer);
#endif

  if ((strcmp((char *)uart3_data_buffer, "help") == 0) ||
      (strcmp((char *)uart3_data_buffer, "?") == 0))
  {
    M100P_SendRemoteHelp();
  }
  else if (strcmp((char *)uart3_data_buffer, "ping") == 0)
  {
    M100P_SendReply("OK pong");
  }
  else if (strcmp((char *)uart3_data_buffer, "status") == 0)
  {
    M100P_SendRemoteStatus();
  }
  else if (strncmp((char *)uart3_data_buffer, "canmode", 7U) == 0)
  {
    uint8_t mode = 0U;
    const char *mode_name = NULL;
    char *args = (char *)uart3_data_buffer + 7;

    if (DebugUart_ParseCanMode(args, &mode, &mode_name) == 0U)
    {
      M100P_SendReply("ERR usage: canmode [speed|current|pos]");
    }
    else if (CanMotor_SetModeAll(mode) == HAL_OK)
    {
      M100P_SendReply("OK canmode %s", mode_name);
    }
    else
    {
      M100P_SendReply("ERR canmode failed");
    }
  }
  else if (strncmp((char *)uart3_data_buffer, "canrpm ", 7U) == 0)
  {
    char *args = (char *)uart3_data_buffer + 7;
    char *rpm_str;
    unsigned long motor_id;
    float rpm;

    motor_id = strtoul(args, &rpm_str, 10);
    if (rpm_str != args)
    {
      rpm = strtof(rpm_str, &rpm_str);
      if (CanMotor_SetSpeedRpm((uint8_t)motor_id, rpm) == HAL_OK)
      {
        M100P_MarkMotionAlive((rpm != 0.0f) ? 1U : 0U);
        M100P_SendReply("OK canrpm %lu %.2f", motor_id, rpm);
      }
      else
      {
        M100P_SendReply("ERR canrpm failed");
      }
    }
    else
    {
      M100P_SendReply("ERR usage: canrpm <id> <rpm>");
    }
  }
  else if (strncmp((char *)uart3_data_buffer, "can4 ", 5U) == 0)
  {
    char *cursor = (char *)uart3_data_buffer + 5;
    float rpm1;
    float rpm2;
    float rpm3;
    float rpm4;

    if ((DebugUart_ParseNextFloat(&cursor, &rpm1) != 0U) &&
        (DebugUart_ParseNextFloat(&cursor, &rpm2) != 0U) &&
        (DebugUart_ParseNextFloat(&cursor, &rpm3) != 0U) &&
        (DebugUart_ParseNextFloat(&cursor, &rpm4) != 0U))
    {
      if (CanMotor_SetSpeedRpm4(rpm1, rpm2, rpm3, rpm4) == HAL_OK)
      {
        M100P_MarkMotionAlive(((rpm1 != 0.0f) || (rpm2 != 0.0f) || (rpm3 != 0.0f) || (rpm4 != 0.0f)) ? 1U : 0U);
        M100P_SendReply("OK can4 %.2f %.2f %.2f %.2f", rpm1, rpm2, rpm3, rpm4);
      }
      else
      {
        M100P_SendReply("ERR can4 failed");
      }
    }
    else
    {
      M100P_SendReply("ERR usage: can4 <rpm1> <rpm2> <rpm3> <rpm4>");
    }
  }
  else if (strncmp((char *)uart3_data_buffer, "carfwd ", 7U) == 0)
  {
    float rpm;

    if (DebugUart_ParseSingleRpmArg((char *)uart3_data_buffer + 7, &rpm) != 0U)
    {
      if (CanMotor_MoveForward(rpm) == HAL_OK)
      {
        M100P_MarkMotionAlive((rpm != 0.0f) ? 1U : 0U);
        M100P_SendReply("OK carfwd %.2f", rpm);
      }
      else
      {
        M100P_SendReply("ERR carfwd failed");
      }
    }
    else
    {
      M100P_SendReply("ERR usage: carfwd <rpm>");
    }
  }
  else if (strncmp((char *)uart3_data_buffer, "carback ", 8U) == 0)
  {
    float rpm;

    if (DebugUart_ParseSingleRpmArg((char *)uart3_data_buffer + 8, &rpm) != 0U)
    {
      if (CanMotor_MoveBackward(rpm) == HAL_OK)
      {
        M100P_MarkMotionAlive((rpm != 0.0f) ? 1U : 0U);
        M100P_SendReply("OK carback %.2f", rpm);
      }
      else
      {
        M100P_SendReply("ERR carback failed");
      }
    }
    else
    {
      M100P_SendReply("ERR usage: carback <rpm>");
    }
  }
  else if (strncmp((char *)uart3_data_buffer, "carleft ", 8U) == 0)
  {
    float rpm;

    if (DebugUart_ParseSingleRpmArg((char *)uart3_data_buffer + 8, &rpm) != 0U)
    {
      if (CanMotor_TurnLeft(rpm) == HAL_OK)
      {
        M100P_MarkMotionAlive((rpm != 0.0f) ? 1U : 0U);
        M100P_SendReply("OK carleft %.2f", rpm);
      }
      else
      {
        M100P_SendReply("ERR carleft failed");
      }
    }
    else
    {
      M100P_SendReply("ERR usage: carleft <rpm>");
    }
  }
  else if (strncmp((char *)uart3_data_buffer, "carright ", 9U) == 0)
  {
    float rpm;

    if (DebugUart_ParseSingleRpmArg((char *)uart3_data_buffer + 9, &rpm) != 0U)
    {
      if (CanMotor_TurnRight(rpm) == HAL_OK)
      {
        M100P_MarkMotionAlive((rpm != 0.0f) ? 1U : 0U);
        M100P_SendReply("OK carright %.2f", rpm);
      }
      else
      {
        M100P_SendReply("ERR carright failed");
      }
    }
    else
    {
      M100P_SendReply("ERR usage: carright <rpm>");
    }
  }
  else if (strcmp((char *)uart3_data_buffer, "carstop") == 0)
  {
    if (CanMotor_StopAll() == HAL_OK)
    {
      M100P_MarkMotionAlive(0U);
      M100P_SendReply("OK carstop");
    }
    else
    {
      M100P_SendReply("ERR carstop failed");
    }
  }
  else if (strncmp((char *)uart3_data_buffer, "canstop ", 8U) == 0)
  {
    char *args = (char *)uart3_data_buffer + 8;
    char *end_ptr;
    unsigned long motor_id;

    motor_id = strtoul(args, &end_ptr, 10);
    if (end_ptr != args)
    {
      if (CanMotor_Stop((uint8_t)motor_id) == HAL_OK)
      {
        M100P_MarkMotionAlive(0U);
        M100P_SendReply("OK canstop %lu", motor_id);
      }
      else
      {
        M100P_SendReply("ERR canstop failed");
      }
    }
    else
    {
      M100P_SendReply("ERR usage: canstop <id>");
    }
  }
  else if (strcmp((char *)uart3_data_buffer, "canstopall") == 0)
  {
    if (CanMotor_StopAll() == HAL_OK)
    {
      M100P_MarkMotionAlive(0U);
      M100P_SendReply("OK canstopall");
    }
    else
    {
      M100P_SendReply("ERR canstopall failed");
    }
  }
  else if (strcmp((char *)uart3_data_buffer, "canrx") == 0)
  {
    CanMotor_PrintLastRx(&huart3);
  }
  else
  {
    M100P_SendReply("ERR unknown: %s", uart3_data_buffer);
  }

  memset(uart3_data_buffer, 0, uart_data_len + 1U);
}

static void DebugUart_HandleCommand(void)
{
#if !HWT101_VOFA_MODE
  uint16_t uart_data_len = Uart_ReadFrame(&uart1_ring_buffer, uart1_data_buffer);

  if (uart_data_len == 0U)
  {
    return;
  }

  uart_data_len = Uart_TrimLineEndings(uart1_data_buffer, uart_data_len);
  if (uart_data_len == 0U)
  {
    return;
  }

  if (strcmp((char *)uart1_data_buffer, "help") == 0)
  {
    my_printf(&huart1, "[UART1] commands: help, zero, hwzero, status, dht, light, send6, at, ati, csq, m100p <cmd>, canmode [speed|current|pos], canrpm <id> <rpm>, can4 <r1> <r2> <r3> <r4>, carfwd <rpm>, carback <rpm>, carleft <rpm>, carright <rpm>, carstop, canstop <id>, canstopall, canrx\r\n");
  }
  else if (strcmp((char *)uart1_data_buffer, "at") == 0)
  {
    M100P_SendAtLine("AT");
  }
  else if (strcmp((char *)uart1_data_buffer, "ati") == 0)
  {
    M100P_SendAtLine("ATI");
  }
  else if (strcmp((char *)uart1_data_buffer, "csq") == 0)
  {
    M100P_SendAtLine("AT+CSQ");
  }
  else if (strcmp((char *)uart1_data_buffer, "zero") == 0)
  {
    if (g_hwt101_ready && g_hwt101.data.data_valid)
    {
      Hwt101_CaptureZero(g_hwt101.data.yaw, "soft_zero");
    }
    else
    {
      my_printf(&huart1, "[HWT101] soft zero failed, no valid IMU data\r\n");
    }
  }
  else if (strcmp((char *)uart1_data_buffer, "hwzero") == 0)
  {
    if (g_hwt101_ready && (HWT101_ResetYaw(&g_hwt101) == 0))
    {
      g_yaw_zero = 0.0f;
      g_yaw_zero_valid = 1U;
      my_printf(&huart1, "[HWT101] hardware yaw reset command sent\r\n");
    }
    else
    {
      my_printf(&huart1, "[HWT101] hardware yaw reset failed\r\n");
    }
  }
  else if (strcmp((char *)uart1_data_buffer, "status") == 0)
  {
    if (g_hwt101_ready && g_hwt101.data.data_valid)
    {
      my_printf(
        &huart1,
        "[IMU] yaw_raw=%.2f deg yaw_zero=%.2f deg yaw_rel=%.2f deg gyro_z=%.2f dps ts=%lu\r\n",
        g_hwt101.data.yaw,
        g_yaw_zero,
        g_yaw_zero_valid ? Hwt101_NormalizeAngle(g_hwt101.data.yaw - g_yaw_zero) : 0.0f,
        g_hwt101.data.gyro_z,
        g_hwt101.data.timestamp);
    }
    else
    {
      my_printf(&huart1, "[IMU] no valid data yet\r\n");
    }

    if (Dht11_IsOnline(DHT11_GetData(&g_dht11), HAL_GetTick()) != 0U)
    {
      DHT11_Data_t *dht11_data = DHT11_GetData(&g_dht11);
      my_printf(
        &huart1,
        "[DHT11] humidity=%.1f %% temperature=%.1f C ts=%lu\r\n",
        dht11_data->humidity,
        dht11_data->temperature,
        dht11_data->timestamp);
    }
    else
    {
      my_printf(&huart1, "[DHT11] no valid data yet\r\n");
    }

    if (Light_IsOnline(Light_GetData(&g_light), HAL_GetTick()) != 0U)
    {
      Light_Data_t *light_data = Light_GetData(&g_light);
      my_printf(
        &huart1,
        "[LIGHT] raw=%u level=%.1f %% ts=%lu\r\n",
        light_data->raw,
        light_data->level_percent,
        light_data->timestamp);
    }
    else
    {
      my_printf(&huart1, "[LIGHT] no valid data yet\r\n");
    }
  }
  else if (strcmp((char *)uart1_data_buffer, "dht") == 0)
  {
    if (g_dht11_ready && (DHT11_Read(&g_dht11) == 0))
    {
      DHT11_Data_t *dht11_data = DHT11_GetData(&g_dht11);
      my_printf(
        &huart1,
        "[DHT11] humidity=%.1f %% temperature=%.1f C ts=%lu\r\n",
        dht11_data->humidity,
        dht11_data->temperature,
        dht11_data->timestamp);
    }
    else
    {
      my_printf(&huart1, "[DHT11] read failed err=%d\r\n", g_dht11.last_error);
    }
  }
  else if (strcmp((char *)uart1_data_buffer, "light") == 0)
  {
    if (g_light_ready && (Light_Read(&g_light) == 0))
    {
      Light_Data_t *light_data = Light_GetData(&g_light);
      my_printf(
        &huart1,
        "[LIGHT] raw=%u level=%.1f %% ts=%lu\r\n",
        light_data->raw,
        light_data->level_percent,
        light_data->timestamp);
    }
    else
    {
      my_printf(&huart1, "[LIGHT] read failed\r\n");
    }
  }
  else if (strncmp((char *)uart1_data_buffer, "m100p ", 6U) == 0)
  {
    M100P_SendAtLine((char *)&uart1_data_buffer[6]);
  }
  else if (strcmp((char *)uart1_data_buffer, "send6") == 0)
  {
    my_printf(&huart1, "[UART1] send6 -> UART6 status\r\n");
    Uart6_SendStatusFrame();
    my_printf(&huart1, "[UART1] send6 done\r\n");
  }
  else if (strncmp((char *)uart1_data_buffer, "canmode", 7U) == 0)
  {
    uint8_t mode = 0U;
    const char *mode_name = NULL;
    char *args = (char *)uart1_data_buffer + 7;

    if (DebugUart_ParseCanMode(args, &mode, &mode_name) == 0U)
    {
      my_printf(&huart1, "[CAN1] usage: canmode [speed|current|pos]\r\n");
    }
    else if (CanMotor_SetModeAll(mode) == HAL_OK)
    {
      my_printf(&huart1, "[CAN1] set all slots to %s mode\r\n", mode_name);
    }
    else
    {
      my_printf(&huart1, "[CAN1] set mode failed\r\n");
    }
  }
  else if (strncmp((char *)uart1_data_buffer, "canrpm ", 7U) == 0)
  {
    char *args = (char *)uart1_data_buffer + 7;
    char *rpm_str;
    unsigned long motor_id;
    float rpm;

    motor_id = strtoul(args, &rpm_str, 10);
    if (rpm_str != args)
    {
      rpm = strtof(rpm_str, &rpm_str);
      if (CanMotor_SetSpeedRpm((uint8_t)motor_id, rpm) == HAL_OK)
      {
        my_printf(&huart1, "[CAN1] motor=%lu rpm=%.2f\r\n", motor_id, rpm);
      }
      else
      {
        my_printf(&huart1, "[CAN1] canrpm failed, check motor id and CAN ready\r\n");
      }
    }
    else
    {
      my_printf(&huart1, "[CAN1] usage: canrpm <id> <rpm>\r\n");
    }
  }
  else if (strncmp((char *)uart1_data_buffer, "can4 ", 5U) == 0)
  {
    char *cursor = (char *)uart1_data_buffer + 5;
    float rpm1;
    float rpm2;
    float rpm3;
    float rpm4;

    if ((DebugUart_ParseNextFloat(&cursor, &rpm1) != 0U) &&
        (DebugUart_ParseNextFloat(&cursor, &rpm2) != 0U) &&
        (DebugUart_ParseNextFloat(&cursor, &rpm3) != 0U) &&
        (DebugUart_ParseNextFloat(&cursor, &rpm4) != 0U))
    {
      if (CanMotor_SetSpeedRpm4(rpm1, rpm2, rpm3, rpm4) == HAL_OK)
      {
        my_printf(
          &huart1,
          "[CAN1] group rpm=%.2f %.2f %.2f %.2f\r\n",
          rpm1,
          rpm2,
          rpm3,
          rpm4);
      }
      else
      {
        my_printf(&huart1, "[CAN1] can4 failed, check CAN ready\r\n");
      }
    }
    else
    {
      my_printf(&huart1, "[CAN1] usage: can4 <rpm1> <rpm2> <rpm3> <rpm4>\r\n");
    }
  }
  else if (strncmp((char *)uart1_data_buffer, "carfwd ", 7U) == 0)
  {
    float rpm;

    if (DebugUart_ParseSingleRpmArg((char *)uart1_data_buffer + 7, &rpm) != 0U)
    {
      if (CanMotor_MoveForward(rpm) == HAL_OK)
      {
        my_printf(&huart1, "[CAR] forward rpm=%.2f\r\n", rpm);
      }
      else
      {
        my_printf(&huart1, "[CAR] carfwd failed\r\n");
      }
    }
    else
    {
      my_printf(&huart1, "[CAR] usage: carfwd <rpm>\r\n");
    }
  }
  else if (strncmp((char *)uart1_data_buffer, "carback ", 8U) == 0)
  {
    float rpm;

    if (DebugUart_ParseSingleRpmArg((char *)uart1_data_buffer + 8, &rpm) != 0U)
    {
      if (CanMotor_MoveBackward(rpm) == HAL_OK)
      {
        my_printf(&huart1, "[CAR] backward rpm=%.2f\r\n", rpm);
      }
      else
      {
        my_printf(&huart1, "[CAR] carback failed\r\n");
      }
    }
    else
    {
      my_printf(&huart1, "[CAR] usage: carback <rpm>\r\n");
    }
  }
  else if (strncmp((char *)uart1_data_buffer, "carleft ", 8U) == 0)
  {
    float rpm;

    if (DebugUart_ParseSingleRpmArg((char *)uart1_data_buffer + 8, &rpm) != 0U)
    {
      if (CanMotor_TurnLeft(rpm) == HAL_OK)
      {
        my_printf(&huart1, "[CAR] turn left rpm=%.2f\r\n", rpm);
      }
      else
      {
        my_printf(&huart1, "[CAR] carleft failed\r\n");
      }
    }
    else
    {
      my_printf(&huart1, "[CAR] usage: carleft <rpm>\r\n");
    }
  }
  else if (strncmp((char *)uart1_data_buffer, "carright ", 9U) == 0)
  {
    float rpm;

    if (DebugUart_ParseSingleRpmArg((char *)uart1_data_buffer + 9, &rpm) != 0U)
    {
      if (CanMotor_TurnRight(rpm) == HAL_OK)
      {
        my_printf(&huart1, "[CAR] turn right rpm=%.2f\r\n", rpm);
      }
      else
      {
        my_printf(&huart1, "[CAR] carright failed\r\n");
      }
    }
    else
    {
      my_printf(&huart1, "[CAR] usage: carright <rpm>\r\n");
    }
  }
  else if (strcmp((char *)uart1_data_buffer, "carstop") == 0)
  {
    if (CanMotor_StopAll() == HAL_OK)
    {
      my_printf(&huart1, "[CAR] stop\r\n");
    }
    else
    {
      my_printf(&huart1, "[CAR] carstop failed\r\n");
    }
  }
  else if (strncmp((char *)uart1_data_buffer, "canstop ", 8U) == 0)
  {
    char *args = (char *)uart1_data_buffer + 8;
    char *end_ptr;
    unsigned long motor_id;

    motor_id = strtoul(args, &end_ptr, 10);
    if (end_ptr != args)
    {
      if (CanMotor_Stop((uint8_t)motor_id) == HAL_OK)
      {
        my_printf(&huart1, "[CAN1] motor=%lu stop\r\n", motor_id);
      }
      else
      {
        my_printf(&huart1, "[CAN1] canstop failed\r\n");
      }
    }
    else
    {
      my_printf(&huart1, "[CAN1] usage: canstop <id>\r\n");
    }
  }
  else if (strcmp((char *)uart1_data_buffer, "canstopall") == 0)
  {
    if (CanMotor_StopAll() == HAL_OK)
    {
      my_printf(&huart1, "[CAN1] all motors stop\r\n");
    }
    else
    {
      my_printf(&huart1, "[CAN1] canstopall failed\r\n");
    }
  }
  else if (strcmp((char *)uart1_data_buffer, "canrx") == 0)
  {
    CanMotor_PrintLastRx(&huart1);
  }
  else
  {
    my_printf(&huart1, "[UART1] unknown command: %s\r\n", uart1_data_buffer);
  }

  memset(uart1_data_buffer, 0, uart_data_len + 1U);
#endif
}

static void CanMotor_PrintLastRx(UART_HandleTypeDef *reply_uart)
{
#if !HWT101_VOFA_MODE
  const CanMotor_LastRx_t *last_rx = CanMotor_GetLastRx();
  CanMotor_ChassisFeedback_t chassis_feedback;
  uint8_t motor_online;
  uint32_t now_tick = HAL_GetTick();

  if ((CanMotor_IsReady() == 0U) || (last_rx == NULL) || (last_rx->valid == 0U))
  {
    my_printf(reply_uart, "[CAN1] no rx frame cached yet\r\n");
    return;
  }

  my_printf(
    reply_uart,
    "[CAN1] last_rx id=0x%03lX dlc=%u data=%02X %02X %02X %02X %02X %02X %02X %02X tick=%lu age=%lu ms count=%lu\r\n",
    last_rx->id,
    last_rx->dlc,
    last_rx->data[0],
    last_rx->data[1],
    last_rx->data[2],
    last_rx->data[3],
    last_rx->data[4],
    last_rx->data[5],
    last_rx->data[6],
    last_rx->data[7],
    last_rx->tick_ms,
    now_tick - last_rx->tick_ms,
    last_rx->rx_count);

  motor_online = CanMotor_GetChassisFeedback(&chassis_feedback);
  my_printf(
    reply_uart,
    "[CAN1] chassis motor_online=%u mask=0x%02X left=%d mm/s right=%d mm/s fault=0x%02X\r\n",
    motor_online,
    chassis_feedback.fresh_motor_mask,
    chassis_feedback.left_speed_mmps,
    chassis_feedback.right_speed_mmps,
    chassis_feedback.fault_code);

  for (uint8_t motor_id = 1U; motor_id <= 4U; motor_id++)
  {
    const CanMotor_Feedback_t *feedback = CanMotor_GetFeedback(motor_id);
    uint32_t age_ms = 0U;
    const char *state = "none";

    if ((feedback == NULL) || (feedback->valid == 0U))
    {
      my_printf(reply_uart, "[CAN1] motor%u feedback: none\r\n", motor_id);
      continue;
    }

    age_ms = now_tick - feedback->tick_ms;
    state = (age_ms <= 200U) ? "fresh" : "stale";

    my_printf(
      reply_uart,
      "[CAN1] motor%u state=%s raw=%d motor_rpm=%.2f physical_rpm=%.2f speed=%d mm/s fault=0x%02X mode=0x%02X tick=%lu age=%lu ms count=%lu\r\n",
      motor_id,
      state,
      feedback->speed_raw,
      feedback->motor_rpm,
      feedback->physical_rpm,
      feedback->physical_speed_mmps,
      feedback->fault_code,
      feedback->mode,
      feedback->tick_ms,
      age_ms,
      feedback->rx_count);
  }
#endif
}

static uint16_t Uart_ReadFrame(struct rt_ringbuffer *ring, uint8_t *buffer)
{
  uint16_t data_len = rt_ringbuffer_data_len(ring);

  if (data_len == 0)
  {
    return 0;
  }

  if (data_len >= BUFFER_SIZE)
  {
    data_len = BUFFER_SIZE - 1;
  }

  rt_ringbuffer_get(ring, buffer, data_len);
  buffer[data_len] = '\0';
  return data_len;
}

static void Uart_StartRxDma(
  struct rt_ringbuffer *ring,
  uint8_t *pool,
  UART_HandleTypeDef *uart,
  uint8_t *dma_buffer,
  DMA_HandleTypeDef *dma)
{
  rt_ringbuffer_init(ring, pool, BUFFER_SIZE);
  HAL_UARTEx_ReceiveToIdle_DMA(uart, dma_buffer, BUFFER_SIZE);
  __HAL_DMA_DISABLE_IT(dma, DMA_IT_HT);
}

void Uart1_Init(void)
{
  Uart_StartRxDma(
    &uart1_ring_buffer,
    uart1_ring_buffer_pool,
    &huart1,
    uart1_rx_dma_buffer,
    &hdma_usart1_rx);
  DebugUart_SendStartupBanner();
}

void Uart1_Task(void)
{
  UartDriver_ServiceRxHealth();
  DebugUart_Heartbeat();
  DebugUart_HandleCommand();
}

void Uart2_Init(void)
{
  Uart_StartRxDma(
    &uart2_ring_buffer,
    uart2_ring_buffer_pool,
    &huart2,
    uart2_rx_dma_buffer,
    &hdma_usart2_rx);
}

void Uart3_Init(void)
{
  Uart3_InternalInit();
}

void Uart2_Task(void)
{
  uint16_t uart_data_len = Uart_ReadFrame(&uart2_ring_buffer, uart2_data_buffer);
  if (uart_data_len > 0)
  {
    Hwt101_ProcessRxFrame(uart2_data_buffer, uart_data_len);
    memset(uart2_data_buffer, 0, uart_data_len);
  }

  Hwt101_ReportData();
}

void Uart3_Task(void)
{
  Uart3_InternalTask();
}

void Uart6_Init(void)
{
  Uart_StartRxDma(
    &uart6_ring_buffer,
    uart6_ring_buffer_pool,
    &huart6,
    uart6_rx_dma_buffer,
    &hdma_usart6_rx);
}

void Uart6_Task(void)
{
  Uart6_HandleRequest();
  Uart6_CheckControlTimeout();
}

void Uart_Init(void)
{
  Uart1_Init();
  Uart2_Init();
  Uart3_Init();
  Uart6_Init();
  Hwt101_AppInit();
  Dht11_AppInit();
  Light_AppInit();
}

void Uart_Task(void)
{
  Uart1_Task();
  Uart2_Task();
  Uart3_Task();
  Uart6_Task();
  Dht11_Task();
  Light_Task();
}
