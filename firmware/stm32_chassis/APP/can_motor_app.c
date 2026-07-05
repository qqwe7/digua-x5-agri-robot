#include "can_motor_app.h"
#include "MyDefine.h"

#define CAN_MOTOR_BITRATE_HINT     500000U
#define CAN_MOTOR_MAX_RPM          210.0f
#define CAN_MOTOR_MODE_CURRENT     0x01U
#define CAN_MOTOR_MODE_SPEED       0x02U
#define CAN_MOTOR_MODE_POSITION    0x03U
#define CAN_MOTOR_RX_DEBUG         0U
#define CAN_MOTOR_BOOT_DEMO        0U
#define CAN_MOTOR_BOOT_DEMO_ID     1U
#define CAN_MOTOR_BOOT_DEMO_RPM    10.0f
#define CAN_MOTOR_BOOT_DEMO_MS     3000U
#define CAN_MOTOR_SIGN_LF          1.0f
#define CAN_MOTOR_SIGN_RF         -1.0f
#define CAN_MOTOR_SIGN_LR          1.0f
#define CAN_MOTOR_SIGN_RR         -1.0f
#define CAN_MOTOR_TURN_GAIN        5.0f
#define CAN_MOTOR_TURN_FWD_GAIN    1.00f
#define CAN_MOTOR_TURN_REV_GAIN    1.00f
#define CAN_MOTOR_FEEDBACK_BASE_ID 0x96U
#define CAN_MOTOR_FEEDBACK_COUNT   4U
#define CAN_MOTOR_FEEDBACK_STALE_MS 200U
#define CAN_MOTOR_PI               3.1415926f
#define CAN_MOTOR_WHEEL_DIAMETER_MM 150.0f
#define CAN_MOTOR_TRACK_WIDTH_MM   300.0f
#define CAN_MOTOR_WHEEL_CIRCUMFERENCE_MM (CAN_MOTOR_PI * CAN_MOTOR_WHEEL_DIAMETER_MM)

static uint8_t g_can_motor_ready = 0U;
static CanMotor_LastRx_t g_can_motor_last_rx = {0};
static CanMotor_Feedback_t g_can_motor_feedback[CAN_MOTOR_FEEDBACK_COUNT] = {0};

static void CanMotor_FillModePayload(uint8_t payload[8], uint8_t mode);
static HAL_StatusTypeDef CanMotor_SendStd(uint32_t std_id, const uint8_t payload[8], uint8_t dlc);
static HAL_StatusTypeDef CanMotor_BuildSpeedPayload(uint8_t motor_id, float rpm, uint32_t *std_id, uint8_t payload[8]);
static HAL_StatusTypeDef CanMotor_BuildSpeedPayload4(float rpm1, float rpm2, float rpm3, float rpm4, uint8_t payload[8]);
static int16_t CanMotor_RpmToRaw(float rpm);
static float CanMotor_AbsRpm(float rpm);
static float CanMotor_GetPhysicalSign(uint8_t motor_id);
static int16_t CanMotor_DecodeI16BE(const uint8_t *data);
static int16_t CanMotor_ClampI16FromFloat(float value);
static int16_t CanMotor_RpmToPhysicalSpeedMmps(float physical_rpm);
static float CanMotor_MmpsToPhysicalRpm(float speed_mmps);
static uint8_t CanMotor_IsFeedbackFresh(const CanMotor_Feedback_t *feedback, uint32_t now_tick);
static void CanMotor_RecordRx(const CAN_RxHeaderTypeDef *header, const uint8_t data[8]);

void CanMotor_Init(void)
{
  CAN_FilterTypeDef filter = {0};

  filter.FilterBank = 0;
  filter.FilterMode = CAN_FILTERMODE_IDMASK;
  filter.FilterScale = CAN_FILTERSCALE_32BIT;
  filter.FilterIdHigh = 0x0000;
  filter.FilterIdLow = 0x0000;
  filter.FilterMaskIdHigh = 0x0000;
  filter.FilterMaskIdLow = 0x0000;
  filter.FilterFIFOAssignment = CAN_FILTER_FIFO0;
  filter.FilterActivation = ENABLE;
  filter.SlaveStartFilterBank = 14;

  if (HAL_CAN_ConfigFilter(&hcan1, &filter) != HAL_OK)
  {
    my_printf(&huart1, "[CAN1] filter config failed\r\n");
    return;
  }

  if (HAL_CAN_Start(&hcan1) != HAL_OK)
  {
    my_printf(&huart1, "[CAN1] start failed\r\n");
    return;
  }

  g_can_motor_ready = 1U;
  my_printf(&huart1, "[CAN1] ready on PB8/PB9, target bitrate=%lu\r\n", CAN_MOTOR_BITRATE_HINT);
  my_printf(&huart1, "[CAN1] debug cmds: canmode [speed|current|pos], canrpm <id> <rpm>, can4 <r1> <r2> <r3> <r4>, carfwd <rpm>, carback <rpm>, carleft <rpm>, carright <rpm>, carstop, canstop <id>, canstopall, canrx\r\n");

#if CAN_MOTOR_BOOT_DEMO
  CanMotor_SetModeAll(CAN_MOTOR_MODE_SPEED);
  HAL_Delay(50U);
  CanMotor_SetSpeedRpm(CAN_MOTOR_BOOT_DEMO_ID, CAN_MOTOR_BOOT_DEMO_RPM);
  HAL_Delay(CAN_MOTOR_BOOT_DEMO_MS);
  CanMotor_Stop(CAN_MOTOR_BOOT_DEMO_ID);
#endif
}

void CanMotor_Task(void)
{
  CAN_RxHeaderTypeDef rx_header;
  uint8_t rx_data[8];

  if (g_can_motor_ready == 0U)
  {
    return;
  }

  while (HAL_CAN_GetRxFifoFillLevel(&hcan1, CAN_RX_FIFO0) > 0U)
  {
    if (HAL_CAN_GetRxMessage(&hcan1, CAN_RX_FIFO0, &rx_header, rx_data) == HAL_OK)
    {
      CanMotor_RecordRx(&rx_header, rx_data);
#if CAN_MOTOR_RX_DEBUG
      my_printf(
        &huart1,
        "[CAN1 RX] id=0x%03lX dlc=%u data=%02X %02X %02X %02X %02X %02X %02X %02X\r\n",
        rx_header.StdId,
        rx_header.DLC,
        rx_data[0],
        rx_data[1],
        rx_data[2],
        rx_data[3],
        rx_data[4],
        rx_data[5],
        rx_data[6],
        rx_data[7]);
#endif
    }
  }
}

uint8_t CanMotor_IsReady(void)
{
  return g_can_motor_ready;
}

HAL_StatusTypeDef CanMotor_SetModeAll(uint8_t mode)
{
  uint8_t payload[8];

  CanMotor_FillModePayload(payload, mode);
  return CanMotor_SendStd(0x105U, payload, 8U);
}

HAL_StatusTypeDef CanMotor_SetSpeedRpm(uint8_t motor_id, float rpm)
{
  uint32_t std_id = 0U;
  uint8_t payload[8];
  HAL_StatusTypeDef status;

  status = CanMotor_BuildSpeedPayload(motor_id, rpm, &std_id, payload);
  if (status != HAL_OK)
  {
    return status;
  }

  return CanMotor_SendStd(std_id, payload, 8U);
}

HAL_StatusTypeDef CanMotor_SetSpeedRpm4(float rpm1, float rpm2, float rpm3, float rpm4)
{
  uint8_t payload[8];

  if (CanMotor_BuildSpeedPayload4(rpm1, rpm2, rpm3, rpm4, payload) != HAL_OK)
  {
    return HAL_ERROR;
  }

  return CanMotor_SendStd(0x32U, payload, 8U);
}

HAL_StatusTypeDef CanMotor_SetWheelPhysicalRpm4(float rpm_lf, float rpm_rf, float rpm_lr, float rpm_rr)
{
  return CanMotor_SetSpeedRpm4(
    rpm_lf * CAN_MOTOR_SIGN_LF,
    rpm_rf * CAN_MOTOR_SIGN_RF,
    rpm_lr * CAN_MOTOR_SIGN_LR,
    rpm_rr * CAN_MOTOR_SIGN_RR);
}

HAL_StatusTypeDef CanMotor_MoveForward(float rpm)
{
  rpm = CanMotor_AbsRpm(rpm);
  return CanMotor_SetWheelPhysicalRpm4(rpm, rpm, rpm, rpm);
}

HAL_StatusTypeDef CanMotor_MoveBackward(float rpm)
{
  rpm = CanMotor_AbsRpm(rpm);
  return CanMotor_SetWheelPhysicalRpm4(-rpm, -rpm, -rpm, -rpm);
}

HAL_StatusTypeDef CanMotor_TurnLeft(float rpm)
{
  float turn_rpm = rpm * CAN_MOTOR_TURN_GAIN;
  float left_rpm = turn_rpm * CAN_MOTOR_TURN_REV_GAIN;
  float right_rpm = turn_rpm * CAN_MOTOR_TURN_FWD_GAIN;

  /* Spin left in place: left wheels backward, right wheels forward. */
  return CanMotor_SetWheelPhysicalRpm4(-left_rpm, right_rpm, -left_rpm, right_rpm);
}

HAL_StatusTypeDef CanMotor_TurnRight(float rpm)
{
  float turn_rpm = rpm * CAN_MOTOR_TURN_GAIN;
  float left_rpm = turn_rpm * CAN_MOTOR_TURN_FWD_GAIN;
  float right_rpm = turn_rpm * CAN_MOTOR_TURN_REV_GAIN;

  /* Spin right in place: left wheels forward, right wheels backward. */
  return CanMotor_SetWheelPhysicalRpm4(left_rpm, -right_rpm, left_rpm, -right_rpm);
}

HAL_StatusTypeDef CanMotor_Stop(uint8_t motor_id)
{
  return CanMotor_SetSpeedRpm(motor_id, 0.0f);
}

HAL_StatusTypeDef CanMotor_StopAll(void)
{
  return CanMotor_SetSpeedRpm4(0.0f, 0.0f, 0.0f, 0.0f);
}

HAL_StatusTypeDef CanMotor_SetChassisVelocityMmps(int16_t linear_mmps, int16_t angular_cdegps)
{
  float linear = (float)linear_mmps;
  float angular_radps = ((float)angular_cdegps) * CAN_MOTOR_PI / 18000.0f;
  float half_track = CAN_MOTOR_TRACK_WIDTH_MM * 0.5f;
  float left_mmps = linear - (angular_radps * half_track);
  float right_mmps = linear + (angular_radps * half_track);
  float left_rpm = CanMotor_MmpsToPhysicalRpm(left_mmps);
  float right_rpm = CanMotor_MmpsToPhysicalRpm(right_mmps);

  return CanMotor_SetWheelPhysicalRpm4(left_rpm, right_rpm, left_rpm, right_rpm);
}

const CanMotor_LastRx_t *CanMotor_GetLastRx(void)
{
  return &g_can_motor_last_rx;
}

const CanMotor_Feedback_t *CanMotor_GetFeedback(uint8_t motor_id)
{
  if ((motor_id < 1U) || (motor_id > CAN_MOTOR_FEEDBACK_COUNT))
  {
    return NULL;
  }

  return &g_can_motor_feedback[motor_id - 1U];
}

uint8_t CanMotor_GetChassisFeedback(CanMotor_ChassisFeedback_t *feedback)
{
  uint32_t now_tick = HAL_GetTick();
  int32_t left_sum = 0;
  int32_t right_sum = 0;

  if (feedback == NULL)
  {
    return 0U;
  }

  memset(feedback, 0, sizeof(*feedback));

  for (uint8_t i = 0U; i < CAN_MOTOR_FEEDBACK_COUNT; i++)
  {
    const CanMotor_Feedback_t *motor = &g_can_motor_feedback[i];

    if (CanMotor_IsFeedbackFresh(motor, now_tick) == 0U)
    {
      continue;
    }

    feedback->fresh_motor_mask |= (uint8_t)(1U << i);
    if (motor->tick_ms > feedback->newest_tick_ms)
    {
      feedback->newest_tick_ms = motor->tick_ms;
    }
    if ((feedback->fault_code == 0U) && (motor->fault_code != 0U))
    {
      feedback->fault_code = motor->fault_code;
    }

    if ((i == 0U) || (i == 2U))
    {
      left_sum += motor->physical_speed_mmps;
      feedback->left_valid_count++;
    }
    else
    {
      right_sum += motor->physical_speed_mmps;
      feedback->right_valid_count++;
    }
  }

  if (feedback->left_valid_count != 0U)
  {
    feedback->left_speed_mmps = (int16_t)(left_sum / (int32_t)feedback->left_valid_count);
  }

  if (feedback->right_valid_count != 0U)
  {
    feedback->right_speed_mmps = (int16_t)(right_sum / (int32_t)feedback->right_valid_count);
  }

  return (feedback->fresh_motor_mask == 0x0FU) ? 1U : 0U;
}

static void CanMotor_FillModePayload(uint8_t payload[8], uint8_t mode)
{
  for (uint8_t i = 0U; i < 8U; i++)
  {
    payload[i] = mode;
  }
}

static HAL_StatusTypeDef CanMotor_SendStd(uint32_t std_id, const uint8_t payload[8], uint8_t dlc)
{
  CAN_TxHeaderTypeDef tx_header = {0};
  uint32_t tx_mailbox;

  if (g_can_motor_ready == 0U)
  {
    return HAL_ERROR;
  }

  tx_header.StdId = std_id;
  tx_header.ExtId = 0U;
  tx_header.IDE = CAN_ID_STD;
  tx_header.RTR = CAN_RTR_DATA;
  tx_header.DLC = dlc;
  tx_header.TransmitGlobalTime = DISABLE;

  return HAL_CAN_AddTxMessage(&hcan1, &tx_header, (uint8_t *)payload, &tx_mailbox);
}

static HAL_StatusTypeDef CanMotor_BuildSpeedPayload(uint8_t motor_id, float rpm, uint32_t *std_id, uint8_t payload[8])
{
  int16_t value;
  uint8_t slot;

  if ((motor_id < 1U) || (motor_id > 8U))
  {
    return HAL_ERROR;
  }

  value = CanMotor_RpmToRaw(rpm);
  memset(payload, 0, 8U);
  slot = (uint8_t)(((motor_id - 1U) % 4U) * 2U);
  payload[slot] = (uint8_t)((value >> 8) & 0xFF);
  payload[slot + 1U] = (uint8_t)(value & 0xFF);
  *std_id = (motor_id <= 4U) ? 0x32U : 0x33U;

  return HAL_OK;
}

static HAL_StatusTypeDef CanMotor_BuildSpeedPayload4(float rpm1, float rpm2, float rpm3, float rpm4, uint8_t payload[8])
{
  int16_t raw[4];
  uint8_t i;

  raw[0] = CanMotor_RpmToRaw(rpm1);
  raw[1] = CanMotor_RpmToRaw(rpm2);
  raw[2] = CanMotor_RpmToRaw(rpm3);
  raw[3] = CanMotor_RpmToRaw(rpm4);

  memset(payload, 0, 8U);
  for (i = 0U; i < 4U; i++)
  {
    uint8_t slot = (uint8_t)(i * 2U);
    payload[slot] = (uint8_t)((raw[i] >> 8) & 0xFF);
    payload[slot + 1U] = (uint8_t)(raw[i] & 0xFF);
  }

  return HAL_OK;
}

static int16_t CanMotor_RpmToRaw(float rpm)
{
  if (rpm > CAN_MOTOR_MAX_RPM)
  {
    rpm = CAN_MOTOR_MAX_RPM;
  }
  else if (rpm < (-CAN_MOTOR_MAX_RPM))
  {
    rpm = -CAN_MOTOR_MAX_RPM;
  }

  return (int16_t)(rpm * 100.0f);
}

static float CanMotor_AbsRpm(float rpm)
{
  return (rpm < 0.0f) ? (-rpm) : rpm;
}

static float CanMotor_GetPhysicalSign(uint8_t motor_id)
{
  switch (motor_id)
  {
    case 1U:
      return CAN_MOTOR_SIGN_LF;
    case 2U:
      return CAN_MOTOR_SIGN_RF;
    case 3U:
      return CAN_MOTOR_SIGN_LR;
    case 4U:
      return CAN_MOTOR_SIGN_RR;
    default:
      return 1.0f;
  }
}

static int16_t CanMotor_DecodeI16BE(const uint8_t *data)
{
  uint16_t value = (uint16_t)(((uint16_t)data[0] << 8U) | data[1]);
  return (int16_t)value;
}

static int16_t CanMotor_ClampI16FromFloat(float value)
{
  if (value > 32767.0f)
  {
    return 32767;
  }

  if (value < -32768.0f)
  {
    return -32768;
  }

  return (int16_t)((value >= 0.0f) ? (value + 0.5f) : (value - 0.5f));
}

static int16_t CanMotor_RpmToPhysicalSpeedMmps(float physical_rpm)
{
  return CanMotor_ClampI16FromFloat(physical_rpm * CAN_MOTOR_WHEEL_CIRCUMFERENCE_MM / 60.0f);
}

static float CanMotor_MmpsToPhysicalRpm(float speed_mmps)
{
  return speed_mmps * 60.0f / CAN_MOTOR_WHEEL_CIRCUMFERENCE_MM;
}

static uint8_t CanMotor_IsFeedbackFresh(const CanMotor_Feedback_t *feedback, uint32_t now_tick)
{
  if ((feedback == NULL) || (feedback->valid == 0U))
  {
    return 0U;
  }

  return ((now_tick - feedback->tick_ms) <= CAN_MOTOR_FEEDBACK_STALE_MS) ? 1U : 0U;
}

static void CanMotor_RecordRx(const CAN_RxHeaderTypeDef *header, const uint8_t data[8])
{
  uint8_t motor_id;
  CanMotor_Feedback_t *feedback;

  g_can_motor_last_rx.id = header->StdId;
  g_can_motor_last_rx.dlc = header->DLC;
  memcpy(g_can_motor_last_rx.data, data, 8U);
  g_can_motor_last_rx.tick_ms = HAL_GetTick();
  g_can_motor_last_rx.rx_count++;
  g_can_motor_last_rx.valid = 1U;

  if ((header->IDE != CAN_ID_STD) || (header->DLC < 8U))
  {
    return;
  }

  if ((header->StdId <= CAN_MOTOR_FEEDBACK_BASE_ID) ||
      (header->StdId > (CAN_MOTOR_FEEDBACK_BASE_ID + CAN_MOTOR_FEEDBACK_COUNT)))
  {
    return;
  }

  motor_id = (uint8_t)(header->StdId - CAN_MOTOR_FEEDBACK_BASE_ID);
  feedback = &g_can_motor_feedback[motor_id - 1U];
  feedback->motor_id = motor_id;
  feedback->speed_raw = CanMotor_DecodeI16BE(&data[0]);
  feedback->torque_current_raw = CanMotor_DecodeI16BE(&data[2]);
  feedback->position_raw = (uint16_t)CanMotor_DecodeI16BE(&data[4]);
  feedback->fault_code = data[6];
  feedback->mode = data[7];
  feedback->motor_rpm = ((float)feedback->speed_raw) / 100.0f;
  feedback->physical_rpm = feedback->motor_rpm * CanMotor_GetPhysicalSign(motor_id);
  feedback->physical_speed_mmps = CanMotor_RpmToPhysicalSpeedMmps(feedback->physical_rpm);
  feedback->tick_ms = g_can_motor_last_rx.tick_ms;
  feedback->rx_count++;
  feedback->valid = 1U;
}
