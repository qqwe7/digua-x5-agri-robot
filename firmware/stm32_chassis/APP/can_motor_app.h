#ifndef __CAN_MOTOR_APP_H__
#define __CAN_MOTOR_APP_H__

#include "main.h"

typedef struct
{
  uint32_t id;
  uint8_t dlc;
  uint8_t data[8];
  uint32_t tick_ms;
  uint32_t rx_count;
  uint8_t valid;
} CanMotor_LastRx_t;

typedef struct
{
  uint8_t motor_id;
  uint8_t valid;
  int16_t speed_raw;
  int16_t torque_current_raw;
  uint16_t position_raw;
  uint8_t fault_code;
  uint8_t mode;
  float motor_rpm;
  float physical_rpm;
  int16_t physical_speed_mmps;
  uint32_t tick_ms;
  uint32_t rx_count;
} CanMotor_Feedback_t;

typedef struct
{
  int16_t left_speed_mmps;
  int16_t right_speed_mmps;
  uint8_t left_valid_count;
  uint8_t right_valid_count;
  uint8_t fresh_motor_mask;
  uint8_t fault_code;
  uint32_t newest_tick_ms;
} CanMotor_ChassisFeedback_t;

void CanMotor_Init(void);
void CanMotor_Task(void);
uint8_t CanMotor_IsReady(void);
HAL_StatusTypeDef CanMotor_SetModeAll(uint8_t mode);
HAL_StatusTypeDef CanMotor_SetSpeedRpm(uint8_t motor_id, float rpm);
HAL_StatusTypeDef CanMotor_SetSpeedRpm4(float rpm1, float rpm2, float rpm3, float rpm4);
HAL_StatusTypeDef CanMotor_SetWheelPhysicalRpm4(float rpm_lf, float rpm_rf, float rpm_lr, float rpm_rr);
HAL_StatusTypeDef CanMotor_MoveForward(float rpm);
HAL_StatusTypeDef CanMotor_MoveBackward(float rpm);
HAL_StatusTypeDef CanMotor_TurnLeft(float rpm);
HAL_StatusTypeDef CanMotor_TurnRight(float rpm);
HAL_StatusTypeDef CanMotor_Stop(uint8_t motor_id);
HAL_StatusTypeDef CanMotor_StopAll(void);
HAL_StatusTypeDef CanMotor_SetChassisVelocityMmps(int16_t linear_mmps, int16_t angular_cdegps);
const CanMotor_LastRx_t *CanMotor_GetLastRx(void);
const CanMotor_Feedback_t *CanMotor_GetFeedback(uint8_t motor_id);
uint8_t CanMotor_GetChassisFeedback(CanMotor_ChassisFeedback_t *feedback);

#endif
