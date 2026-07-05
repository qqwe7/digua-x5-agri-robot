/**
  ******************************************************************************
  * @file    robot.c
  * @brief   This file provides code for the robot control frame.
  ******************************************************************************
  */

#include "robot.h"
#include "task.h"
#include "cmsis_os.h"
#include "stdbool.h"
#include "stdio.h"
#include "string.h"
#include "Emm_V5.h"
#include "usart.h"
#include "main.h"
#include "robot_kinematics.h"
#include <stdlib.h>
#include "robot_cmd.h"
#include "esp8266_mqtt.h"

struct robot g_robot;       /* robot瀹炰緥 */

/* 鏈烘鑷傚悇鍏宠妭DH鍙傛暟, 闇€鎵嬪姩璁剧疆 */
const float D_H[6][4] = {{0,        0,          0,          M_PI/2},
                         {0,        M_PI/2,      0,         M_PI/2},
                         {200,      M_PI,        0,         -M_PI/2},
                         {47.63,    -M_PI/2,     -184.5,    0},
                         {0,        M_PI/2,      0,         M_PI/2},
                         {0,        M_PI/2,        0,         0}};

/* 鏈烘鑷傚浣嶇姸鎬佷笅T0_6鐭╅樀, 闇€鎵嬪姩璁剧疆 */
const float T_0_6_reset[4][4] = {
    {0, -1, 0, 0},
    {0, 0, -1, -47.63},
    {1, 0, 0, 15.5},
    {0, 0, 0, 1},
};

/* 鍚勫叧鑺傛棆杞殑鏉冮噸, 闇€鎵嬪姩璁剧疆 */
const float joint_weight[ROBOT_MAX_JOINT_NUM] = {5, 3, 3, 1, 1, 1};

/* 鏈烘鑷傚悇鍏宠妭鍒濆鐘舵€? 闇€鎵嬪姩璁剧疆 */
static struct joint g_joints_init[ROBOT_MAX_JOINT_NUM] = {
    {90,    MOTOR_DIR_CCW,   50,     JOINT_LIMIT_1_GPIO_Port,    JOINT_LIMIT_1_Pin,      0,      360,    DIR_NEGATIVE},  /* 鍏宠妭1 */
    {90,    MOTOR_DIR_CW,  50.89,  JOINT_LIMIT_2_GPIO_Port,    JOINT_LIMIT_2_Pin,       0,      180,    DIR_NEGATIVE},  /* 鍏宠妭2 */
    {-90,   MOTOR_DIR_CW,   50.89,  JOINT_LIMIT_3_GPIO_Port,    JOINT_LIMIT_3_Pin,      -180,   90 ,    DIR_NEGATIVE},  /* 鍏宠妭3 */
    {0,     MOTOR_DIR_CW,  51,     JOINT_LIMIT_4_GPIO_Port,    JOINT_LIMIT_4_Pin,       -90,   90,    DIR_NEGATIVE},  /* 鍏宠妭4 */
    {90,    MOTOR_DIR_CCW,   26.85,  JOINT_LIMIT_5_GPIO_Port,    JOINT_LIMIT_5_Pin,     0,      90,     DIR_POSITIVE},  /* 鍏宠妭5 */
    {0,     MOTOR_DIR_CW,   51,     JOINT_LIMIT_6_GPIO_Port,    JOINT_LIMIT_6_Pin,      0,      360,    DIR_NEGATIVE},  /* 鍏宠妭6 */
};

static const uint32_t g_joint_motor_steps_per_rev[ROBOT_MAX_JOINT_NUM] = {
	ROBOT_MOTOR_STEPS_PER_REV,
	ROBOT_MOTOR_STEPS_PER_REV,
	ROBOT_MOTOR_STEPS_PER_REV,
	ROBOT_MOTOR_STEPS_PER_REV,
	ROBOT_MOTOR_STEPS_PER_REV,
	ROBOT_MOTOR_STEPS_PER_REV,
};

static const bool g_joint_has_limit_switch[ROBOT_MAX_JOINT_NUM] = {
	false,
	true,
	true,
	true,
	true,
	true,
};

volatile struct robot_remote_control g_remote_control = {0};
static volatile bool g_robot_power_on_auto_reset_enable = true;

#define ROBOT_AUTO_PATH_MAX_POINTS 256
#define ROBOT_TEACH_POINT_MAX_NUM 8

static struct position g_auto_path_buf[ROBOT_AUTO_PATH_MAX_POINTS];
static float g_auto_result_buf[ROBOT_AUTO_PATH_MAX_POINTS * ROBOT_MAX_JOINT_NUM];
static float g_robot_teach_points[ROBOT_TEACH_POINT_MAX_NUM][ROBOT_MAX_JOINT_NUM];
static bool g_robot_teach_valid[ROBOT_TEACH_POINT_MAX_NUM] = {0};

static struct position *robot_path_interpolation_linear(struct position *target, int *size);
static int robot_update_current_angle(uint8_t joint_id);
static int robot_angle_map(float angle, float min_angle, float max_angle, float *result);
static float robot_angle_diff(float cur_angle, float target_angle);
static void robot_joint_stop(uint8_t joint_id);
static void robot_joint_stop_quick(uint8_t joint_id);
static int time_func_circle(uint32_t time_ms, struct position *pos);
static int robot_pid_run(struct position *path, int path_size, float *result);
static void robot_pid_one_period(float *target_angle, float *intg_error, float *pre_error, float *total_error, int joint_num);
static int robot_pid_remote(void);
static int robot_mqtt_joints_sync(void);
static void robot_joint_stop_from_isr(uint8_t joint_id);
static bool robot_delay_abortable(uint32_t delay_ms);
static uint32_t robot_motion_wait_time_ms(uint8_t joint_id, float angle, float velocity);
static bool robot_assist_reset_move_rel(uint8_t joint_id, float rel_angle, bool ignore_soft_limit);
static int robot_assist_reset_read_angle(uint8_t joint_id, float *angle, uint8_t retry_count);
static int robot_assist_reset_read_position_error(uint8_t joint_id, float *angle_error);
static bool robot_assist_reset_commit_reference(uint8_t joint_id);
static bool robot_assist_reset_commit_reference_no_stop(uint8_t joint_id);
static bool robot_assist_reset_touch_joint(uint8_t joint_id, float max_neg_angle, float backoff_angle);
static void robot_assist_reset(struct robot_event *event);

struct robot_joint_motion_cmd {
	uint8_t dir;
	uint16_t velocity;
	uint32_t steps;
	float next_angle;
	bool should_send;
};

static float robot_joint_cmd_velocity(uint8_t joint_id)
{
	if (joint_id == 0U) {
		return 3.0f;
	}

	return ROBOT_JOINT_DEFAULT_VELOCITY;
}

static uint8_t robot_joint_cmd_acceleration(uint8_t joint_id)
{
	if (joint_id == 0U) {
		return 20U;
	}

	return ROBOT_JOINT_DEFAULT_ACCELERATION;
}

static int robot_joint_prepare_position_command(uint32_t joint_id, enum dir dir, float angle, float velocity,
	bool absolute, bool ignore_soft_limit, struct robot_joint_motion_cmd *cmd)
{
	if ((joint_id >= ROBOT_MAX_JOINT_NUM) || (cmd == NULL)) {
		return 1;
	}

	if (velocity < 0) {
		LOG("ERROR: velocity is negative");
		return 1;
	}

	float rel_angle = 0;
	float target_angle = 0;
	float mapped_current = 0;
	uint8_t motor_dir = 0;
	int ret = 0;
	struct joint *joint = &g_robot.joints[joint_id];

	if (!ignore_soft_limit &&
		!((g_joints_init[joint_id].min_angle == 0) && (g_joints_init[joint_id].max_angle == 360))) {
		ret = robot_angle_map(joint->current_angle,
			g_joints_init[joint_id].min_angle,
			g_joints_init[joint_id].max_angle,
			&mapped_current);
		if (ret != 0) {
			mapped_current = joint->current_angle;
		}

		target_angle = absolute ? angle : (mapped_current + ((dir == DIR_POSITIVE) ? angle : -angle));
		if ((target_angle < g_joints_init[joint_id].min_angle) || (target_angle > g_joints_init[joint_id].max_angle)) {
			LOG("joint[%d] software limit hit, current:%.2f target:%.2f range:[%.2f, %.2f]\n",
				joint_id,
				mapped_current,
				target_angle,
				g_joints_init[joint_id].min_angle,
				g_joints_init[joint_id].max_angle);
			return 1;
		}
	}

	if (absolute) {
		rel_angle = angle - joint->current_angle;

		if (fabs(rel_angle) < ROBOT_JOINT_ANGLE_ERROR_RANGE) {
			cmd->next_angle = joint->current_angle;
			cmd->should_send = false;
			return 0;
		}

		motor_dir = (dir == DIR_POSITIVE) ? joint->postive_direction : !(joint->postive_direction);

		if ((rel_angle < 0) && (dir != DIR_NEGATIVE)) {
			rel_angle = 360 - fabs(rel_angle);
		} else if ((rel_angle > 0) && (dir != DIR_POSITIVE)) {
			rel_angle = 360 - fabs(rel_angle);
		}

		cmd->next_angle = angle;
	} else {
		rel_angle = angle;
		motor_dir = (dir == DIR_POSITIVE) ? joint->postive_direction : !(joint->postive_direction);
		if (rel_angle < 0) {
			motor_dir = !motor_dir;
		}

		cmd->next_angle = joint->current_angle + ((dir == DIR_POSITIVE) ? angle : -angle);
	}

	uint32_t motor_steps_per_rev = (joint->motor_steps_per_rev != 0U) ? joint->motor_steps_per_rev : ROBOT_MOTOR_STEPS_PER_REV;
	cmd->steps = (uint32_t)fabs(round(rel_angle * joint->reduction_ratio * motor_steps_per_rev / 360.0f));
	cmd->dir = motor_dir;
	cmd->velocity = (uint16_t)fabsf(velocity * 600.0f * joint->reduction_ratio / 360.0f);
	cmd->should_send = (cmd->steps > 0U);
	return 0;
}

static robot_time_func g_robot_time_func = time_func_circle; /* 鏃堕棿鍑芥暟 */

static void robot_joint_limit_post_handle(uint8_t joint_id)
{
	vTaskDelay(200); // 寤舵椂200ms绛夊緟闄愪綅寮€鍏崇ǔ瀹?
	taskENTER_CRITICAL();
	// 娓呴櫎闄愪綅鐘舵€佷綅
	ROBOT_STATUS_CLEAR(g_robot.joints[joint_id].status, ROBOT_STATUS_LIMIT_HAPPENED);
	taskEXIT_CRITICAL();
}

uint32_t robot_joint_veloccity_to(uint32_t joint_id, float velocity,\
    uint8_t acceleration)
{
	if (joint_id >= ROBOT_MAX_JOINT_NUM) {
        return 1;
    }

	int start_tick = HAL_GetTick();
    struct joint *joint = &g_robot.joints[joint_id];
	
	uint8_t dir = (velocity > 0) ? joint->postive_direction : !(joint->postive_direction);
	ROBOT_STATUS_CLEAR(joint->status, ROBOT_STATUS_LIMIT_ENABLE);
	uint32_t addr = joint_id + 1; // 鍚勫叧鑺侰AN鍦板潃浠?寮€濮?

	// 璁＄畻鐢垫満閫熷害锛屽崟浣嶏細rpm. 椹卞姩鍣ㄤ細灏哶velocity/10浣滀负鐪熷疄閫熷害锛屼粠鑰屽疄鐜?.1RPM绮惧害鎺у埗锛屽洜姝よ绠楁椂鎴戜滑闇€瑕佹彁鍓嶄箻浠?0
	joint->velocity = velocity;
	uint16_t _velocity = (uint16_t)fabs(velocity * 600 * joint->reduction_ratio / 360);
	// 鍏充换鍔¤皟搴?
	vTaskSuspendAll();
	can.rxFrameFlag = false;
	while(can.rxFrameFlag == false) {
		if ((HAL_GetTick() - start_tick) > ROBOT_CAN_TIMEOUT) {
			LOG("ERROR: CAN timeout:%d\n", joint_id);
			xTaskResumeAll();
			return 1;
		}
		Emm_V5_Vel_Control(addr, dir, _velocity, acceleration, false);
		HAL_Delay(1);
	}
	xTaskResumeAll();
	return 0;
}

/* 鎺у埗鍏宠妭杩愬姩 */
static uint32_t robot_joint_rotate_to(uint32_t joint_id, enum dir dir, float angle, float velocity,\
    uint32_t acceleration, bool absolute)
{
	struct robot_joint_motion_cmd cmd = {0};
	struct joint *joint = &g_robot.joints[joint_id];
	uint32_t addr = joint_id + 1; // 鍚勫叧鑺侰AN鍦板潃浠?寮€濮?

	if (robot_joint_prepare_position_command(joint_id, dir, angle, velocity, absolute, false, &cmd) != 0) {
		return 1;
	}

	if (!cmd.should_send) {
		return 0;
	}

	ROBOT_STATUS_CLEAR(joint->status, ROBOT_STATUS_READY);
	Emm_V5_Pos_Control(addr, cmd.dir, cmd.velocity, (uint8_t)acceleration, cmd.steps, false, false);
	joint->current_angle = cmd.next_angle;
	return 0;
}

static void robot_joint_limit_happend(uint8_t joint_id)
{
	if (g_robot.event_queue == NULL) {
        return;
    }

	if ((joint_id >= ROBOT_MAX_JOINT_NUM) || (!g_joint_has_limit_switch[joint_id])) {
		return;
	}

    // 闄愪綅寮€鍏虫湭浣胯兘
    if (!ROBOT_STATUS_IS(g_robot.joints[joint_id].status, ROBOT_STATUS_LIMIT_ENABLE)) {
        return;
    }

	// 闃叉鎸夐敭鎶栧姩锛岄噸澶嶅彂浜嬩欢
    if (ROBOT_STATUS_IS(g_robot.joints[joint_id].status, ROBOT_STATUS_LIMIT_HAPPENED)) {
        return;
	}

	// 璇ュ嚱鏁颁粎浼氬湪涓柇涓皟鐢紝涓斾笉瀛樺湪澶氫釜涓柇鍚屾椂骞跺彂璁剧疆涓€涓叧鑺傜姸鎬佷綅鐨勬儏鍐碉紝鍥犳鏃犻渶浣跨敤涓寸晫鍖轰繚鎶?
	robot_joint_stop_from_isr(joint_id);
	ROBOT_STATUS_SET(g_robot.joints[joint_id].status, ROBOT_STATUS_LIMIT_HAPPENED);

	struct robot_event event = {0};
	event.type = ROBOT_LIMIT_SWITCH_EVENT;
	event.joint_id = joint_id;
	BaseType_t xHigherPriorityTaskWoken;
    xQueueSendToBackFromISR(g_robot.event_queue, &event, &xHigherPriorityTaskWoken);
}

static void robot_joint_limit_set_input(uint8_t joint_id)
{
	// 淇敼涓鸿緭鍏ユā寮?
    HAL_GPIO_DeInit(g_robot.joints[joint_id].limit_gpio_port, g_robot.joints[joint_id].limit_gpio_pin);
    GPIO_InitTypeDef GPIO_InitStruct = {0};
    GPIO_InitStruct.Pin = g_robot.joints[joint_id].limit_gpio_pin;
    GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
    GPIO_InitStruct.Pull = GPIO_PULLUP;
    HAL_GPIO_Init(g_robot.joints[joint_id].limit_gpio_port, &GPIO_InitStruct);
}

static void robot_joint_limit_set_irq(uint8_t joint_id)
{
	// 璁剧疆涓轰笂涓嬪崌娌胯Е鍙?
    HAL_GPIO_DeInit(g_robot.joints[joint_id].limit_gpio_port, g_robot.joints[joint_id].limit_gpio_pin);
    GPIO_InitTypeDef GPIO_InitStruct = {0};
    GPIO_InitStruct.Pin = g_robot.joints[joint_id].limit_gpio_pin;
    GPIO_InitStruct.Mode = GPIO_MODE_IT_RISING_FALLING;
    GPIO_InitStruct.Pull = GPIO_PULLUP;
    HAL_GPIO_Init(g_robot.joints[joint_id].limit_gpio_port, &GPIO_InitStruct);
}

static GPIO_PinState robot_get_limit_status(uint8_t joint_id)
{   
    // 璇诲彇闄愪綅寮€鍏崇姸鎬?
    GPIO_PinState state = HAL_GPIO_ReadPin(g_robot.joints[joint_id].limit_gpio_port, g_robot.joints[joint_id].limit_gpio_pin);
    return state;
}

static void robot_joint_reset(uint8_t joint_id)
{
	GPIO_PinState state;
    int reset_dir = g_robot.joints[joint_id].reset_dir;
    
    robot_joint_limit_set_input(joint_id); // 璁剧疆涓鸿緭鍏ユā寮?
    state = robot_get_limit_status(joint_id); // 璇诲彇闄愪綅寮€鍏崇姸鎬?
    robot_joint_limit_set_irq(joint_id); // 璁剧疆涓轰腑鏂ā寮?

    if (state == GPIO_PIN_SET) { // 闄愪綅寮€鍏冲凡瑙﹀彂, 鏃犻渶澶嶄綅
        LOG("joint %d limit switch already happend\n", joint_id);
        Emm_V5_Reset_CurPos_To_Zero(joint_id + 1); // 鍏宠妭澶嶄綅
        return;
    }

	struct robot_joint_motion_cmd cmd = {0};

	if (robot_joint_prepare_position_command(joint_id, reset_dir, ROBOT_RESET_DEFAULT_ANGLE,
			ROBOT_RESET_DEFAULT_VELOCITY, false, true, &cmd) != 0) {
		return;
	}

	if (!cmd.should_send) {
		return;
	}

	ROBOT_STATUS_CLEAR(g_robot.joints[joint_id].status, ROBOT_STATUS_READY);
	Emm_V5_Pos_Control((uint8_t)(joint_id + 1), cmd.dir, cmd.velocity,
		ROBOT_RESET_DEFAULT_ACCELERATION, cmd.steps, false, false);
	g_robot.joints[joint_id].current_angle = cmd.next_angle;
    // 閫嗘椂閽堟棆杞紝鐩村埌妫€娴嬪埌闄愪綅寮€鍏?
	while (!ROBOT_STATUS_IS(g_robot.joints[joint_id].status, ROBOT_STATUS_LIMIT_HAPPENED)) {
        vTaskDelay(200); // 绛夊緟鍏宠妭杞姩
	}
    vTaskDelay(ROBOT_CAN_DELAY);
    Emm_V5_Reset_CurPos_To_Zero(joint_id + 1); // 鍏宠妭澶嶄綅
}

/* 澶嶄綅鎵€鏈夊叧鑺?*/
static void robot_joint_hard_reset(void)
{   
    // todo: 鍚庨潰涓嶇敤-2锛岀洿鎺ヤ粠ROBOT_MAX_JOINT_NUM - 1寮€濮?
    for (int i = ROBOT_MAX_JOINT_NUM - 2; i >= 0; i--) {
        ROBOT_STATUS_SET(g_robot.joints[i].status, ROBOT_STATUS_LIMIT_ENABLE);
		robot_joint_reset(i);
        vTaskDelay(100);
    }
    
    for (int i = 0; i < ROBOT_MAX_JOINT_NUM; i++) {
        g_robot.joints[i].current_angle = g_joints_init[i].current_angle;
    }
	g_robot.cur_pos.x = 0;
	g_robot.cur_pos.y = 0;
	g_robot.cur_pos.z = 0;
	robot_mqtt_joints_sync();
}

static int robot_angle_map(float angle, float min_angle, float max_angle, float *result)
{
    if (result == NULL) {
		return 1;
	}

    float tmp_angle = angle;

    while (tmp_angle >= 360.0f) {
        tmp_angle -= 360.0f;
    }
    while (tmp_angle < -360.0f) {
        tmp_angle += 360.0f;
    }
	
	// 闃叉瀹炵墿鎶栧姩锛屽鑷撮敊璇垽鏂?
	if (fabs(tmp_angle - min_angle) < ROBOT_JOINT_ANGLE_ERROR_RANGE) {
        tmp_angle = min_angle;
    } else if (fabs(angle - max_angle) < ROBOT_JOINT_ANGLE_ERROR_RANGE) {
        tmp_angle = max_angle;
    }

	if (tmp_angle < min_angle) {
		tmp_angle += 360;
    } else if (tmp_angle > max_angle) {
    	tmp_angle -= 360;
    }

	// 闃叉瀹炵墿鎶栧姩锛屽鑷撮敊璇垽鏂?
	if (fabs(tmp_angle - min_angle) < ROBOT_JOINT_ANGLE_ERROR_RANGE) {
        tmp_angle = min_angle;
    } else if (fabs(tmp_angle - max_angle) < ROBOT_JOINT_ANGLE_ERROR_RANGE) {
        tmp_angle = max_angle;
    }

	if ((tmp_angle < min_angle) || (tmp_angle > max_angle)) {
        return 1;
    }

    *result = tmp_angle;
    return 0;
}

static void robot_joint_soft_reset(void)
{
	float angle = 0;
	int ret = 0;
	for (int i = ROBOT_MAX_JOINT_NUM - 1; i >= 0; i--) {
		ROBOT_STATUS_SET(g_robot.joints[i].status, ROBOT_STATUS_LIMIT_ENABLE);
		int dir = DIR_POSITIVE;
		robot_update_current_angle(i);
		ret = robot_angle_map(g_robot.joints[i].current_angle, g_joints_init[i].min_angle, g_joints_init[i].max_angle, &angle);
		if (ret != 0) {
			LOG("robot angle map failed, joint_id:%d current_angle:%.2f\n", i, g_robot.joints[i].current_angle);
			return;
		}

		if (angle > g_joints_init[i].current_angle) { // 閫嗘椂閽堟棆杞?
			dir = DIR_NEGATIVE;
		}

		if (g_joints_init[i].min_angle == 0 && g_joints_init[i].max_angle == 360) {
			if (fabs(angle - g_joints_init[i].current_angle) > 180) { // 瀵绘壘鏈€灏忚搴?
				dir = -dir;
			}
		}
		
		LOG_FROM_ISR("[%d] current:%.2f, target:%.2f, dir:%d\n\n", i, angle, g_joints_init[i].current_angle, dir);
		g_robot.joints[i].current_angle = angle;

		robot_joint_rotate_to(i, dir, g_joints_init[i].current_angle, ROBOT_RESET_DEFAULT_VELOCITY, ROBOT_RESET_DEFAULT_ACCELERATION, true);
		vTaskDelay(100);
		g_robot.joints[i].current_angle = g_joints_init[i].current_angle;
	}

	g_robot.cur_pos.x = 0;
	g_robot.cur_pos.y = 0;
	g_robot.cur_pos.z = 0;
	robot_mqtt_joints_sync();
}

static bool robot_delay_abortable(uint32_t delay_ms)
{
	while (delay_ms > 0U) {
		uint32_t slice_ms = (delay_ms > 20U) ? 20U : delay_ms;
		if (ROBOT_STATUS_IS(g_robot.status, ROBOT_STATUS_ESTOP)) {
			return false;
		}
		vTaskDelay(slice_ms);
		delay_ms -= slice_ms;
	}

	return !ROBOT_STATUS_IS(g_robot.status, ROBOT_STATUS_ESTOP);
}

static uint32_t robot_motion_wait_time_ms(uint8_t joint_id, float angle, float velocity)
{
	float abs_velocity = fabsf(velocity);
	uint32_t extra_wait_ms = 120U;

	if (abs_velocity < 0.1f) {
		abs_velocity = ROBOT_JOINT_DEFAULT_VELOCITY;
	}

	if (joint_id == 4U) {
		extra_wait_ms = 500U;
	}

	return (uint32_t)((fabsf(angle) / abs_velocity) * 1000.0f) + extra_wait_ms;
}

static bool robot_assist_reset_move_rel(uint8_t joint_id, float rel_angle, bool ignore_soft_limit)
{
	float velocity = robot_joint_cmd_velocity(joint_id);
	uint8_t acceleration = robot_joint_cmd_acceleration(joint_id);
	uint32_t wait_ms = robot_motion_wait_time_ms(joint_id, rel_angle, velocity);
	struct robot_joint_motion_cmd cmd = {0};

	if (robot_joint_prepare_position_command(joint_id, DIR_POSITIVE, rel_angle, velocity,
			false, ignore_soft_limit, &cmd) != 0) {
		LOG("[assist_reset] joint[%u] move failed, rel:%.2f\n", joint_id, rel_angle);
		return false;
	}

	if (!cmd.should_send) {
		return true;
	}

	ROBOT_STATUS_CLEAR(g_robot.joints[joint_id].status, ROBOT_STATUS_READY);
	Emm_V5_Pos_Control((uint8_t)(joint_id + 1), cmd.dir, cmd.velocity, acceleration, cmd.steps, false, false);
	g_robot.joints[joint_id].current_angle = cmd.next_angle;

	return robot_delay_abortable(wait_ms);
}

static int robot_assist_reset_read_angle(uint8_t joint_id, float *angle, uint8_t retry_count)
{
	uint8_t retry_max = (retry_count == 0U) ? 1U : retry_count;

	for (uint8_t i = 0U; i < retry_max; i++) {
		if (robot_refresh_joint_angle(joint_id, angle) == 0) {
			return 0;
		}
		vTaskDelay(ROBOT_CAN_DELAY * 2U);
	}

	return 1;
}

static int robot_assist_reset_read_position_error(uint8_t joint_id, float *angle_error)
{
	uint8_t data[8] = {0};
	uint8_t dlc = 0U;
	float angle = 0.0f;
	struct joint *joint = &g_robot.joints[joint_id];

	if ((joint_id >= ROBOT_MAX_JOINT_NUM) || (angle_error == NULL)) {
		return 1;
	}

	if (robot_read_driver_param(joint_id, S_PERR, data, &dlc) != 0) {
		return 1;
	}

	if ((dlc < 7U) || (data[0] != 0x37U) || (data[6] != 0x6BU)) {
		return 1;
	}

	for (int i = 5; i >= 2; i--) {
		angle += (float)(((uint32_t)data[i]) << ((5 - i) << 3));
	}

	if (data[1] == 0x01U) {
		angle = -angle;
	}

	if (joint->postive_direction == MOTOR_DIR_CCW) {
		angle = -angle;
	}

	*angle_error = angle * 360.0f / 65536.0f / joint->reduction_ratio;
	return 0;
}

static bool robot_assist_reset_commit_reference(uint8_t joint_id)
{
	robot_joint_stop(joint_id);
	vTaskDelay(ROBOT_CAN_DELAY);
	robot_driver_clear_clog(joint_id);
	vTaskDelay(ROBOT_CAN_DELAY);
	Emm_V5_Reset_CurPos_To_Zero((uint8_t)(joint_id + 1));
	g_robot.joints[joint_id].velocity = 0.0f;
	g_robot.joints[joint_id].current_angle = g_joints_init[joint_id].current_angle;
	return robot_delay_abortable(80U);
}

static bool robot_assist_reset_release_and_commit(uint8_t joint_id, float ref_angle, float backoff_angle)
{
	robot_joint_stop_quick(joint_id);
	vTaskDelay(ROBOT_CAN_DELAY);
	robot_driver_clear_clog(joint_id);
	vTaskDelay(ROBOT_CAN_DELAY);
	if ((backoff_angle > 0.0f) && !robot_assist_reset_move_rel(joint_id, backoff_angle, true)) {
		return false;
	}
	Emm_V5_Reset_CurPos_To_Zero((uint8_t)(joint_id + 1));
	g_robot.joints[joint_id].velocity = 0.0f;
	g_robot.joints[joint_id].current_angle = ref_angle;
	return robot_delay_abortable(80U);
}

static bool robot_assist_reset_commit_reference_no_stop(uint8_t joint_id)
{
	robot_driver_clear_clog(joint_id);
	vTaskDelay(ROBOT_CAN_DELAY);
	Emm_V5_Reset_CurPos_To_Zero((uint8_t)(joint_id + 1));
	g_robot.joints[joint_id].velocity = 0.0f;
	g_robot.joints[joint_id].current_angle = g_joints_init[joint_id].current_angle;
	return robot_delay_abortable(80U);
}

static bool robot_assist_reset_touch_joint(uint8_t joint_id, float max_neg_angle, float backoff_angle)
{
	const float step_angle = (joint_id == 1U) ? 2.0f : 5.0f;
	const float moved_threshold = (joint_id == 1U) ? 0.5f : 1.0f;
	const float min_detect_angle = (joint_id == 1U) ? 60.0f : 20.0f;
	const float max_detect_angle = (joint_id == 1U) ? 140.0f : max_neg_angle;
	const float position_error_threshold = (joint_id == 1U) ? 1.0f : 0.0f;
	const uint8_t confirm_count = (joint_id == 1U) ? 3U : 1U;
	const uint8_t read_retry_count = (joint_id == 1U) ? 2U : ((joint_id == 2U) ? 2U : 5U);
	const uint8_t confirm_read_retry_count = (joint_id == 1U) ? 1U : read_retry_count;
	const uint32_t confirm_window_ms = (joint_id == 1U) ? 200U : 0U;
	const uint32_t confirm_interval_ms = (joint_id == 1U) ? 50U : 100U;
	float moved_total = 0.0f;
	float commanded_total = 0.0f;
	float before_angle = 0.0f;
	float after_angle = 0.0f;
	float confirm_angle = 0.0f;
	float step_moved = 0.0f;
	float position_error = 0.0f;
	uint8_t stable_count = 0U;

	if (max_neg_angle <= 0.0f) {
		return true;
	}

	if (robot_assist_reset_read_angle(joint_id, &before_angle, read_retry_count) != 0) {
		if (joint_id == 2U) {
			robot_joint_stop_quick(joint_id);
			vTaskDelay(100U);
			robot_driver_clear_clog(joint_id);
			vTaskDelay(150U);
			if (robot_assist_reset_read_angle(joint_id, &before_angle, 12U) == 0) {
				goto initial_read_ok;
			}
		}
		LOG("[assist_reset] joint[%u] initial read failed\n", joint_id);
		return false;
	}
initial_read_ok:

	while (((joint_id == 1U) ? commanded_total : moved_total) < max_neg_angle) {
		if (!robot_assist_reset_move_rel(joint_id, -step_angle, true)) {
			LOG("[assist_reset] joint[%u] negative search interrupted\n", joint_id);
			return false;
		}
		commanded_total += step_angle;

		if (robot_assist_reset_read_angle(joint_id, &after_angle, read_retry_count) != 0) {
			if ((joint_id == 1U) && (commanded_total >= min_detect_angle) && (commanded_total <= max_detect_angle)) {
				LOG("[assist_reset] joint[%u] read failed in commanded window %.2f, immediate fallback release %.2f then set ref %.2f\n",
					joint_id, commanded_total, backoff_angle, g_joints_init[joint_id].current_angle);
				return robot_assist_reset_release_and_commit(joint_id,
					g_joints_init[joint_id].current_angle, backoff_angle);
			}
			robot_joint_stop_quick(joint_id);
			vTaskDelay(ROBOT_CAN_DELAY);
			if (robot_assist_reset_read_angle(joint_id, &after_angle, read_retry_count) != 0) {
				if (joint_id == 1U) {
					LOG("[assist_reset] joint[%u] read failed during search, force fallback release %.2f then set ref %.2f\n",
						joint_id, backoff_angle, g_joints_init[joint_id].current_angle);
					return robot_assist_reset_release_and_commit(joint_id,
						g_joints_init[joint_id].current_angle, backoff_angle);
				}
				if ((joint_id == 2U) && (moved_total >= min_detect_angle)) {
					LOG("[assist_reset] joint[%u] read failed after detect start, fallback set ref %.2f then lift %.2f\n",
						joint_id, g_joints_init[joint_id].current_angle, backoff_angle);
					if (!robot_assist_reset_commit_reference(joint_id)) {
						return false;
					}
					if (backoff_angle > 0.0f) {
						return robot_assist_reset_move_rel(joint_id, backoff_angle, true);
					}
					return true;
				}
				LOG("[assist_reset] joint[%u] read failed during search\n", joint_id);
				return false;
			}
		}

		step_moved = fabsf(robot_angle_diff(before_angle, after_angle));

		if ((joint_id == 1U) &&
			(commanded_total >= min_detect_angle) &&
			(commanded_total <= max_detect_angle) &&
			(robot_assist_reset_read_position_error(joint_id, &position_error) == 0) &&
			(fabsf(position_error) >= position_error_threshold)) {
			LOG("[assist_reset] joint[%u] touch inferred by pos err %.2f at commanded %.2f, release %.2f then set ref %.2f\n",
				joint_id, position_error, commanded_total, backoff_angle, g_joints_init[joint_id].current_angle);
			return robot_assist_reset_release_and_commit(joint_id,
				g_joints_init[joint_id].current_angle, backoff_angle);
		}

		if (step_moved < moved_threshold) {
			bool detect_ready = false;
			if (joint_id == 1U) {
				detect_ready = (commanded_total >= min_detect_angle) && (commanded_total <= max_detect_angle);
			} else {
				detect_ready = (moved_total >= min_detect_angle);
			}

			if (detect_ready) {
				robot_joint_stop_quick(joint_id);
				vTaskDelay(ROBOT_CAN_DELAY);
				if (joint_id == 1U) {
					robot_driver_clear_clog(joint_id);
					vTaskDelay(ROBOT_CAN_DELAY);
					uint32_t confirm_start = HAL_GetTick();
					confirm_angle = after_angle;
					while ((HAL_GetTick() - confirm_start) < confirm_window_ms) {
						float next_confirm_angle = 0.0f;
						if (robot_assist_reset_read_angle(joint_id, &next_confirm_angle, confirm_read_retry_count) != 0) {
							LOG("[assist_reset] joint[%u] confirm read failed, fallback release %.2f then set ref %.2f\n",
								joint_id, backoff_angle, g_joints_init[joint_id].current_angle);
							return robot_assist_reset_release_and_commit(joint_id,
								g_joints_init[joint_id].current_angle, backoff_angle);
						}
						if (fabsf(robot_angle_diff(confirm_angle, next_confirm_angle)) >= moved_threshold) {
							confirm_angle = next_confirm_angle;
							break;
						}
						confirm_angle = next_confirm_angle;
						vTaskDelay(confirm_interval_ms);
					}

					if ((HAL_GetTick() - confirm_start) >= confirm_window_ms) {
						float probe_angle = confirm_angle;
						if (!robot_assist_reset_move_rel(joint_id, -step_angle, true)) {
							LOG("[assist_reset] joint[%u] probe move interrupted, fallback release %.2f then set ref %.2f\n",
								joint_id, backoff_angle, g_joints_init[joint_id].current_angle);
							return robot_assist_reset_release_and_commit(joint_id,
								g_joints_init[joint_id].current_angle, backoff_angle);
						}
						if (robot_assist_reset_read_angle(joint_id, &probe_angle, read_retry_count) != 0) {
							LOG("[assist_reset] joint[%u] probe read failed, fallback release %.2f then set ref %.2f\n",
								joint_id, backoff_angle, g_joints_init[joint_id].current_angle);
							return robot_assist_reset_release_and_commit(joint_id,
								g_joints_init[joint_id].current_angle, backoff_angle);
						}
						if (fabsf(robot_angle_diff(confirm_angle, probe_angle)) >= moved_threshold) {
							moved_total += fabsf(robot_angle_diff(before_angle, probe_angle));
							before_angle = probe_angle;
							continue;
						}

						robot_joint_stop_quick(joint_id);
						vTaskDelay(ROBOT_CAN_DELAY);
						LOG("[assist_reset] joint[%u] touched stop near %.2f, release %.2f then set ref %.2f\n",
							joint_id, probe_angle, backoff_angle, g_joints_init[joint_id].current_angle);
						return robot_assist_reset_release_and_commit(joint_id,
							g_joints_init[joint_id].current_angle, backoff_angle);
					}

					moved_total += fabsf(robot_angle_diff(before_angle, confirm_angle));
					before_angle = confirm_angle;
					continue;
				}

				stable_count = 0U;
				confirm_angle = after_angle;
				for (uint8_t i = 0U; i < confirm_count; i++) {
					if (robot_assist_reset_read_angle(joint_id, &confirm_angle, read_retry_count) != 0) {
						if ((joint_id == 2U) && (backoff_angle > 0.0f)) {
							LOG("[assist_reset] joint[%u] confirm read failed, fallback set ref %.2f then lift %.2f\n",
								joint_id, g_joints_init[joint_id].current_angle, backoff_angle);
							if (!robot_assist_reset_commit_reference(joint_id)) {
								return false;
							}
							return robot_assist_reset_move_rel(joint_id, backoff_angle, true);
						}
						LOG("[assist_reset] joint[%u] confirm read failed\n", joint_id);
						return false;
					}
					if (fabsf(robot_angle_diff(after_angle, confirm_angle)) < moved_threshold) {
						stable_count++;
						after_angle = confirm_angle;
						vTaskDelay(ROBOT_CAN_DELAY);
						continue;
					}
					break;
				}

				if (stable_count >= confirm_count) {
					if (backoff_angle > 0.0f) {
						if ((joint_id == 2U) || (joint_id == 4U)) {
							LOG("[assist_reset] joint[%u] touched stop near %.2f, set ref %.2f then lift %.2f\n",
								joint_id, confirm_angle, g_joints_init[joint_id].current_angle, backoff_angle);
							if (!robot_assist_reset_commit_reference(joint_id)) {
								return false;
							}
							return robot_assist_reset_move_rel(joint_id, backoff_angle, true);
						}

						LOG("[assist_reset] joint[%u] touched stop near %.2f, release %.2f then set ref %.2f\n",
							joint_id, confirm_angle, backoff_angle, g_joints_init[joint_id].current_angle);
						robot_driver_clear_clog(joint_id);
						vTaskDelay(ROBOT_CAN_DELAY);
						if (!robot_assist_reset_move_rel(joint_id, backoff_angle, true)) {
							return false;
						}
						return robot_assist_reset_commit_reference(joint_id);
					}

					LOG("[assist_reset] joint[%u] touched stop near %.2f, set ref %.2f\n",
						joint_id, confirm_angle, g_joints_init[joint_id].current_angle);
					return robot_assist_reset_commit_reference(joint_id);
				}

				moved_total += fabsf(robot_angle_diff(before_angle, confirm_angle));
				before_angle = confirm_angle;
				continue;
			}
		}

		before_angle = after_angle;
		moved_total += step_moved;
	}

	LOG("[assist_reset] joint[%u] did not touch stop within %.2f deg (moved %.2f, commanded %.2f)\n",
		joint_id, max_neg_angle, moved_total, commanded_total);
	return false;
}

static void robot_assist_reset(struct robot_event *event)
{
	float joint1_neg = 360.0f;
	float joint2_neg = 240.0f;
	float joint1_backoff = 3.0f;
	float joint2_backoff = 3.0f;
	float joint4_prelift = 60.0f;
	float joint4_neg = 120.0f;
	float joint4_backoff = 4.5f;

	if (event != NULL) {
		if (event->param[0] > 0.0f) {
			joint1_neg = event->param[0];
		}
		if (event->param[1] > 0.0f) {
			joint2_neg = event->param[1];
		}
		if (event->param[2] > 0.0f) {
			joint4_prelift = event->param[2];
		}
		if (event->param[3] > 0.0f) {
			joint4_neg = event->param[3];
		}
		if (event->param[4] > 0.0f) {
			joint4_backoff = event->param[4];
		}
	}

	LOG("[assist_reset] start order: joint[4] prelift %.2f -> joint[1] %.2f backoff %.2f -> joint[2] %.2f backoff %.2f (+ joint[3] follow set ref) -> joint[4] %.2f backoff %.2f\n",
		joint4_prelift, joint1_neg, joint1_backoff, joint2_neg, joint2_backoff, joint4_neg, joint4_backoff);

	if (ROBOT_STATUS_IS(g_robot.status, ROBOT_STATUS_ESTOP)) {
		LOG("[assist_reset] aborted: estop active\n");
		return;
	}

	robot_driver_enable((uint8_t)1, true);
	robot_driver_enable((uint8_t)2, true);
	robot_driver_enable((uint8_t)3, true);
	if ((joint4_prelift > 0.0f) || (joint4_neg > 0.0f)) {
		robot_driver_enable((uint8_t)4, true);
	}
	vTaskDelay(ROBOT_CAN_DELAY);

	if ((joint4_prelift > 0.0f) && !robot_assist_reset_move_rel((uint8_t)4, joint4_prelift, true)) {
		LOG("[assist_reset] stopped at step joint[4] prelift\n");
		return;
	}

	LOG("[assist_reset] start step joint[1] touch detect\n");
	if (!robot_assist_reset_touch_joint((uint8_t)1, joint1_neg, joint1_backoff)) {
		LOG("[assist_reset] stopped at step joint[1] touch detect\n");
		return;
	}
	vTaskDelay(800);

	LOG("[assist_reset] start step joint[2] touch detect\n");
	if (!robot_assist_reset_touch_joint((uint8_t)2, joint2_neg, joint2_backoff)) {
		LOG("[assist_reset] stopped at step joint[2] touch detect\n");
		return;
	}
	vTaskDelay(100);

	LOG("[assist_reset] start step joint[3] follow set ref\n");
	if (!robot_assist_reset_commit_reference_no_stop((uint8_t)3)) {
		LOG("[assist_reset] stopped at step joint[3] follow set ref\n");
		return;
	}
	LOG("[assist_reset] joint[3] follow set ref %.2f\n", g_joints_init[3].current_angle);
	vTaskDelay(100);

	LOG("[assist_reset] start step joint[4] touch detect\n");
	if ((joint4_neg > 0.0f) && !robot_assist_reset_touch_joint((uint8_t)4, joint4_neg, joint4_backoff)) {
		LOG("[assist_reset] stopped at step joint[4] touch detect\n");
		return;
	}

	g_robot.cur_pos.x = 0.0f;
	g_robot.cur_pos.y = 0.0f;
	g_robot.cur_pos.z = 0.0f;
	robot_mqtt_joints_sync();
	LOG("[assist_reset] finished\n");
}

static struct position *robot_time_func_path_interpolation(uint32_t time_limit_ms, int *size)
{
    int path_size = 0;
	struct position pos = {0};
	int ret = 0;

    if (g_robot_time_func == NULL) {
        LOG("robot time func is null\n");
		return NULL;	
    }

	path_size = (time_limit_ms / ROBOT_INTERPOLATION_TIME_RESOLUTION); // 璁＄畻璺緞鐐规暟閲?
    struct position *path = (struct position*)malloc(sizeof(struct position) * path_size);
    if (path == NULL) {
        return NULL;
    }

    for (int i = 0; i < path_size; i++) {
        ret = g_robot_time_func(i * ROBOT_INTERPOLATION_TIME_RESOLUTION, &pos);
		if (ret != 0) {
			LOG("robot time func failed\n");
			free(path);
			return NULL;
		}

        path[i].x = pos.x;
        path[i].y = pos.y;
        path[i].z = pos.z;
    }

    *size = path_size;
    return path;
}

static void robot_time_func_move(uint32_t time_limit_ms)
{
	int ret;
	int path_size = 0;

	// 璺緞鎻掑€?
	struct position *path = robot_time_func_path_interpolation(time_limit_ms, &path_size);
    if (path == NULL) {
        LOG("robot time func failed\n");
        return;
    }

	// 璁＄畻鍚勮矾寰勭偣涓嬬殑鍏宠妭瑙掑害
    float *result = (float*)malloc(sizeof(float) * ROBOT_MAX_JOINT_NUM * path_size);
    if (result == NULL) {
        LOG("robot malloc failed\n");
        free(path);
        return;	
    }

	// 鏇存柊褰撳墠鍏宠妭瑙掑害鍒扮畻娉?
    for (int i = 0; i < ROBOT_MAX_JOINT_NUM; i++) {
        robot_kinematics_joint_angle_update_by_id(i, g_robot.joints[i].current_angle);
    }

	for (int i = 0; i < path_size; i++) {
        robot_kinematics_cal_T(T_0_6_reset, g_robot.T, &path[i]);
        ret = robot_kinematics_inverse((float *)g_robot.T, &result[i * ROBOT_MAX_JOINT_NUM], false);
        if (ret != 0) {
            LOG("robot kinematics inverse failed\n");
            free(path);
            free(result);
            return;
        }
		// 鎶婃湰娆¤绠楃殑鍏宠妭瑙掑害鏇存柊鍒扮畻娉曪紝鐢ㄤ簬涓嬫鍏宠妭鏈€浼樿В璁＄畻
		robot_kinematics_joint_angle_update(&result[i * ROBOT_MAX_JOINT_NUM]);
		LOG("[%d] <%.2f %.2f %.2f> ", i, path[i].x, path[i].y, path[i].z);
		LOG("result: ");
		for (int j = 0; j < ROBOT_MAX_JOINT_NUM; j++) {
			LOG("%.2f ", result[i * ROBOT_MAX_JOINT_NUM + j]);
		}
		LOG("\n");
    }

	ret = robot_pid_run(path, path_size, result);
	if (ret == 0) {
		g_robot.cur_pos.x = path[path_size -1].x;
		g_robot.cur_pos.y = path[path_size -1].y;
		g_robot.cur_pos.z = path[path_size -1].z;
	}
	free(path);
	free(result);
}

static void robot_auto_move_interpolation(struct robot_event *event)
{
    int ret;
	// 鎻掑€艰绠楀悇璺緞鐐?
	int path_size = 0;
	struct position *target_pos = (struct position*)event->param;
    struct position *path = robot_path_interpolation_linear(target_pos, &path_size);
    if (path == NULL) {
        LOG("robot path interpolation failed\n");
        return;	
    }

    float *result = g_auto_result_buf;

	// 鏇存柊褰撳墠鍏宠妭瑙掑害鍒扮畻娉?
    for (int i = 0; i < ROBOT_MAX_JOINT_NUM; i++) {
        robot_kinematics_joint_angle_update_by_id(i, g_robot.joints[i].current_angle);
    }

    for (int i = 0; i < path_size; i++) {
        robot_kinematics_cal_T(T_0_6_reset, g_robot.T, &path[i]);
        ret = robot_kinematics_inverse((float *)g_robot.T, &result[i * ROBOT_MAX_JOINT_NUM], false);
        if (ret != 0) {
            LOG("robot kinematics inverse failed\n");
            return;
        }

		// 鎶婃湰娆¤绠楃殑鍏宠妭瑙掑害鏇存柊鍒扮畻娉曪紝鐢ㄤ簬涓嬫鍏宠妭鏈€浼樿В璁＄畻
		robot_kinematics_joint_angle_update(&result[i * ROBOT_MAX_JOINT_NUM]);
		LOG("[%d] <%.2f %.2f %.2f> ", i, path[i].x, path[i].y, path[i].z);
		LOG("result: ");
		for (int j = 0; j < ROBOT_MAX_JOINT_NUM; j++) {
			LOG("%.2f ", result[i * ROBOT_MAX_JOINT_NUM + j]);
		}
		LOG("\n");
    }

	ret = robot_pid_run(path, path_size, result);
	if (ret == 0) {
		g_robot.cur_pos.x = target_pos->x;
		g_robot.cur_pos.y = target_pos->y;
		g_robot.cur_pos.z = target_pos->z;
	}
}

static inline bool robot_joint_is_reach(struct joint *joint, float target_angle)
{
	float current_angle = joint->current_angle;
	if ((joint->velocity == 0) && (fabs(current_angle - target_angle) <= ROBOT_JOINT_ANGLE_ERROR_RANGE)) {	// 閫熷害涓?锛屽綋鍓嶈搴︽帴杩戠洰鏍囪搴︼紝宸茬粡鍒拌揪
		return true;
	}

	if ((joint->velocity < 0) && (current_angle <= (target_angle + ROBOT_JOINT_ANGLE_ERROR_RANGE))) { // 閫熷害涓鸿礋锛屽綋鍓嶈搴﹀皬浜庣洰鏍囪搴︼紝宸茬粡鍒拌揪
		return true;
	}

	if ((joint->velocity > 0) && (current_angle >= (target_angle - ROBOT_JOINT_ANGLE_ERROR_RANGE))) { // 閫熷害涓烘锛屽綋鍓嶈搴﹀ぇ浜庣洰鏍囪搴︼紝宸茬粡鍒拌揪
		return true;
	}

	return false;
}
static float robot_angle_normalize(float angle)
{
	// 榛樿鍏ュ弬瑙掑害鍦?360-720搴﹁寖鍥村唴
	if (angle >= 360) {
		return angle - 360;	
	}

	if (angle < 0) {
		return angle + 360;	
	}
	return angle;
}

/**
 * @brief 璁＄畻褰撳墠瑙掑害涓庣洰鏍囪搴︿箣闂寸殑鏈€灏忓樊鍊硷紝鑰冭檻瑙掑害寰幆銆?
 * 
 * 璇ュ嚱鏁颁細璁＄畻鐩爣瑙掑害涓庡綋鍓嶈搴︾殑宸€硷紝骞跺皢宸€兼槧灏勫埌 -180 搴﹀埌 180 搴︾殑鑼冨洿鍐咃紝
 * 浠ユ纭繚寰楀埌鐨勬槸涓や釜瑙掑害涔嬮棿鐨勬渶灏忓樊鍊硷紝鑰冭檻浜嗚搴﹀湪 0 - 360 搴﹁寖鍥村唴寰幆鐨勭壒鎬с€?
 * 
 * @param cur_angle 褰撳墠瑙掑害锛屽崟浣嶄负搴︺€?
 * @param target_angle 鐩爣瑙掑害锛屽崟浣嶄负搴︺€?
 * @return float 褰撳墠瑙掑害涓庣洰鏍囪搴︿箣闂寸殑鏈€灏忓樊鍊硷紝鍗曚綅涓哄害锛岃寖鍥村湪 -180 搴﹀埌 180 搴︿箣闂淬€?
 */
static float robot_angle_diff(float cur_angle, float target_angle)
{
	float diff = target_angle - cur_angle;
	if (diff > 180) {
		diff -= 360;
	} else if (diff < -180) {
		diff += 360;
	}
	return diff;
}

float g_target_angle[ROBOT_MAX_JOINT_NUM] = {0};
float g_current_angle[ROBOT_MAX_JOINT_NUM] = {0};

static int robot_pid_run(struct position *path, int path_size, float *result)
{
	int p;
	int start_time = 0;
	int node_end_time = 0;
	float target_angle[ROBOT_MAX_JOINT_NUM] = {0};
	float pre_diff[ROBOT_MAX_JOINT_NUM] = {0};
	float intg_diff[ROBOT_MAX_JOINT_NUM] = {0};
	float total_error[ROBOT_MAX_JOINT_NUM] = {0};

	start_time = HAL_GetTick();
	for (p = 1; p < path_size; p++) {
		node_end_time = start_time + ROBOT_INTERPOLATION_TIME_RESOLUTION * p; // 鏈path node缁撴潫鏃堕棿, 涓虹粷瀵规椂闂?
		for (int j = 0; j < ROBOT_MAX_JOINT_NUM; j++) { // 鍒濆鍖?
			target_angle[j] = robot_angle_normalize(result[p * ROBOT_MAX_JOINT_NUM + j]);
			g_target_angle[j] = target_angle[j]; // debug
		}

		while(HAL_GetTick() < node_end_time) { // 绛夊緟鏈path node缁撴潫
			robot_pid_one_period(target_angle, intg_diff, pre_diff, total_error, 6);
		}
		robot_mqtt_joints_sync();
	}

	for (int j = 0; j < ROBOT_MAX_JOINT_NUM; j++) {
		robot_joint_stop(j);
		vTaskDelay(ROBOT_CAN_DELAY);
	}
	for (int j = 0; j < ROBOT_MAX_JOINT_NUM; j++) {
		LOG("[jpint %d] ave_error:%.2f\n", j + 1, total_error[j]/path_size);
	}
	LOG("\nrobot pid run finished!!\n");
	return 0;
}

static void robot_joints_sync_to(struct robot_event *event)
{
	struct robot_joint_motion_cmd cmds[ROBOT_MAX_JOINT_NUM] = {0};
	bool has_motion = false;

	for (int i = 0; i < ROBOT_MAX_JOINT_NUM; i++) {
		if (robot_joint_prepare_position_command((uint32_t)i, DIR_POSITIVE, event->param[i],
				robot_joint_cmd_velocity((uint8_t)i), true, false, &cmds[i]) != 0) {
			return;
		}
		if (cmds[i].should_send) {
			has_motion = true;
		}
	}

	for (int i = 0; i < ROBOT_MAX_JOINT_NUM; i++) {
		if (!cmds[i].should_send) {
			continue;
		}

		ROBOT_STATUS_CLEAR(g_robot.joints[i].status, ROBOT_STATUS_READY);
		Emm_V5_Pos_Control((uint8_t)(i + 1), cmds[i].dir, cmds[i].velocity,
			robot_joint_cmd_acceleration((uint8_t)i), cmds[i].steps, false, true);
		g_robot.joints[i].current_angle = cmds[i].next_angle;
	}

	if (has_motion) {
		Emm_V5_Synchronous_motion(0);
	}
}

static void robot_joints_sync_rel(struct robot_event *event)
{
	struct robot_joint_motion_cmd cmds[ROBOT_MAX_JOINT_NUM] = {0};
	bool has_motion = false;

	for (int i = 0; i < ROBOT_MAX_JOINT_NUM; i++) {
		if (robot_joint_prepare_position_command((uint32_t)i, DIR_POSITIVE, event->param[i],
				robot_joint_cmd_velocity((uint8_t)i), false, false, &cmds[i]) != 0) {
			return;
		}
		if (cmds[i].should_send) {
			has_motion = true;
		}
	}

	for (int i = 0; i < ROBOT_MAX_JOINT_NUM; i++) {
		if (!cmds[i].should_send) {
			continue;
		}

		ROBOT_STATUS_CLEAR(g_robot.joints[i].status, ROBOT_STATUS_READY);
		Emm_V5_Pos_Control((uint8_t)(i + 1), cmds[i].dir, cmds[i].velocity,
			robot_joint_cmd_acceleration((uint8_t)i), cmds[i].steps, false, true);
		g_robot.joints[i].current_angle = cmds[i].next_angle;
	}

	if (has_motion) {
		Emm_V5_Synchronous_motion(0);
	}
}

/**
 * @brief 鏈烘鑷傛帶鍒朵换鍔″嚱鏁帮紝璐熻矗浠庝簨浠堕槦鍒椾腑鎺ユ敹浜嬩欢骞惰繘琛岀浉搴斿鐞嗐€?
 * 
 * 璇ヤ换鍔′細鎸佺画浠庝簨浠堕槦鍒椾腑鑾峰彇鏈烘鑷傜浉鍏充簨浠讹紝鏍规嵁浜嬩欢绫诲瀷璋冪敤涓嶅悓鐨勫鐞嗗嚱鏁帮紝
 * 瀹炵幇瀵规満姊拌噦鍏宠妭杩愬姩銆佽嚜鍔ㄨ繍鍔ㄣ€佸浣嶇瓑鎿嶄綔鐨勬帶鍒躲€?
 * 
 * @param arg 浠诲姟鍙傛暟锛屽湪鏈嚱鏁颁腑鏈娇鐢ㄣ€?
 */
static void robot_control_task(void *arg)
{
	(void)arg;
    LOG("robot control task runing!!!\n");

	vTaskDelay(1000);
	if (g_robot_power_on_auto_reset_enable && !ROBOT_STATUS_IS(g_robot.status, ROBOT_STATUS_ESTOP)) {
		LOG("robot power-on auto reset start\n");
		robot_assist_reset(NULL);
	} else if (!g_robot_power_on_auto_reset_enable) {
		LOG("robot power-on auto reset skipped\n");
	}
    
	struct robot_event event = {0};
	// 浠庨槦鍒椾腑鍙栧嚭浜嬩欢骞跺鐞?
    while(xQueueReceive(g_robot.event_queue, &event, portMAX_DELAY) == pdPASS) {
        switch (event.type) {
            case ROBOT_JOINT_REL_ROTATE:
				LOG("[joint_id: %d] ROBOT_JOINT_REL_ROTATE %f\n", event.joint_id, event.param[0]);
                robot_joint_rotate_to(event.joint_id, DIR_POSITIVE,event.param[0], 
						robot_joint_cmd_velocity(event.joint_id), robot_joint_cmd_acceleration(event.joint_id), false);
                break; 
			case ROBOT_JOINT_ABS_ROTATE:
				LOG("[joint_id: %d] ROBOT_JOINT_ABS_ROTATE %f\n", event.joint_id, event.param[0]);
				robot_joint_rotate_to(event.joint_id, DIR_POSITIVE, event.param[0], 
					robot_joint_cmd_velocity(event.joint_id), robot_joint_cmd_acceleration(event.joint_id), true);
				break;
			case ROBOT_LIMIT_SWITCH_EVENT:
				LOG("[joint_id: %d] ROBOT_LIMIT_SWITCH_EVENT\n", event.joint_id);
				robot_joint_limit_post_handle(event.joint_id);
				break;
			case ROBOT_AUTO_EVENT:
				LOG("ROBOT_AUTO_EVENT\n");
				robot_auto_move_interpolation(&event);
				break;
			case ROBOT_TIMIE_FUNC_EVENT:
				LOG("ROBOT_TIMIE_FUNC_EVENT\n");
				robot_time_func_move((uint32_t)(event.param[0]));
				break;
			case ROBOT_HARD_RESET_EVENT:
				LOG("ROBOT_HARD_RESET_EVENT\n");
				robot_joint_hard_reset();
				break;
			case ROBOT_SOFT_RESET_EVENT:
				LOG("ROBOT_SOFT_RESET_EVENT\n");
				robot_joint_soft_reset();
				break;
			case ROBOT_TEST_EVENT:
				LOG("ROBOT_ASSIST_RESET_EVENT\n");
				robot_assist_reset(&event);
				break;
			case ROBOT_REMOTE_CONTROL_EVENT:
				LOG("ROBOT_REMOTE_CONTROL_EVENT\n");
				robot_pid_remote();
				break;
			case ROBOT_JOINTS_SYNC_EVENT:
				LOG("ROBOT_JOINTS_SYNC_EVENT\n");
				robot_joints_sync_to(&event);
				break;
			case ROBOT_JOINTS_SYNC_REL_EVENT:
				LOG("ROBOT_JOINTS_SYNC_REL_EVENT\n");
				robot_joints_sync_rel(&event);
				break;
			default:
				LOG("robot event type error\n");
        }
    }
}

static void robot_pid_one_period(float *target_angle, float *intg_error, float *pre_error, float *total_error, int joint_num)
{
	float error = 0;
	float v;
	uint32_t pid_end_time = HAL_GetTick() + ROBOT_PID_PERIOD;
	for (int j = 0; j < joint_num; j++) {
		robot_update_current_angle(j);
		g_current_angle[j] = g_robot.joints[j].current_angle; // debug
		error = robot_angle_diff(g_robot.joints[j].current_angle, target_angle[j]);
		intg_error[j] += error;
		if (total_error != NULL) {
			total_error[j] += fabs(error);
		}

		v = ROBOT_PID_KP * error + ROBOT_PID_KI * intg_error[j] + ROBOT_PID_KD * (error - pre_error[j]);
		pre_error[j] = error;
		robot_joint_veloccity_to(j, v, ROBOT_JOINT_DEFAULT_ACCELERATION);
	}

	uint32_t time = HAL_GetTick();
	if (time < pid_end_time) {
		vTaskDelay(pid_end_time - time);
	}
}

struct position g_pos = {0};	// debug
static int robot_pid_remote(void)
{
	uint64_t end_time = 0;
	float target_angle[ROBOT_MAX_JOINT_NUM] = {0};
	float pre_error[ROBOT_MAX_JOINT_NUM] = {0};
	float intg_error[ROBOT_MAX_JOINT_NUM] = {0};
	int ret;
	float T[4][4] = {0};
	int error_count = 0;

	LOG("wait robot reset....\n");
	vTaskDelay(3000);
	LOG("robot into remote mode!!!!\n");

	end_time = HAL_GetTick();
	while(ROBOT_STATUS_IS(g_robot.status, ROBOT_STATUS_RMODE_ENABLE)) {
		end_time += ROBOT_REMOTE_TIME_RESOLUTION; // 鏈璺緞璺熻釜缁撴潫鏃堕棿, 涓虹粷瀵规椂闂?

		// 鏇存柊鐩爣浣嶇疆
		g_pos.x = g_robot.cur_pos.x + g_remote_control.vx * ROBOT_REMOTE_TIME_RESOLUTION / 1000;
		g_pos.y = g_robot.cur_pos.y + g_remote_control.vy * ROBOT_REMOTE_TIME_RESOLUTION / 1000;
		g_pos.z = g_robot.cur_pos.z + g_remote_control.vz * ROBOT_REMOTE_TIME_RESOLUTION / 1000;
		robot_kinematics_cal_T(T_0_6_reset, T, &g_pos);
		ret = robot_kinematics_inverse((float *)T, (float *)&g_remote_control.result[0], false);
		if (ret < 0) {
			error_count++;
			if (error_count >= 10) {
				LOG("robot kinematics inverse failed\n");
				error_count = 0;
			}
			
			for (int j = 0; j < ROBOT_MAX_JOINT_NUM; j++) {
				robot_joint_stop(j);
				vTaskDelay(ROBOT_CAN_DELAY);
			}
			// vTaskDelay(ROBOT_INTERPOLATION_TIME_RESOLUTION);
			continue;
		}
		error_count = 0;
		robot_kinematics_joint_angle_update((float *)&g_remote_control.result[0]);
		g_robot.cur_pos.x = g_pos.x;
		g_robot.cur_pos.y = g_pos.y;
		g_robot.cur_pos.z = g_pos.z;
		robot_joint_veloccity_to(4, g_remote_control.rx, ROBOT_JOINT_DEFAULT_ACCELERATION);
		robot_joint_veloccity_to(5, g_remote_control.ry, ROBOT_JOINT_DEFAULT_ACCELERATION);

		for (int j = 0; j < ROBOT_MAX_JOINT_NUM; j++) { // 鍒濆鍖?
			target_angle[j] = robot_angle_normalize(g_remote_control.result[j]);
			g_target_angle[j] = target_angle[j]; // debug
		}

		while(HAL_GetTick() < end_time) { // 绛夊緟鏈璺緞璺熻釜缁撴潫
			robot_pid_one_period(target_angle, intg_error, pre_error, NULL, 4);
		}
	}

	for (int j = 0; j < ROBOT_MAX_JOINT_NUM; j++) {
		robot_joint_stop(j);
		vTaskDelay(ROBOT_CAN_DELAY);
	}

	LOG("\nrobot remote disable!!\n");
	return 0;
}

/**
 * @brief 鍒濆鍖栨満姊拌噦鎺у埗绯荤粺銆?
 * 
 * 姝ゅ嚱鏁扮敤浜庡畬鎴愭満姊拌噦绯荤粺鐨勫垵濮嬪寲宸ヤ綔锛屽寘鎷垵濮嬪寲鍏宠妭鏁版嵁銆佸垵濮嬩綅濮跨煩闃碉紝
 * 鍒涘缓浜嬩欢闃熷垪浠ュ強鍚姩鏈烘鑷傛帶鍒朵换鍔°€?
 */
void robot_init(void)
{
    /* 鍒濆 */
    memcpy(g_robot.joints, g_joints_init, sizeof(g_joints_init));
    for (int i = 0; i < ROBOT_MAX_JOINT_NUM; i++) {
        g_robot.joints[i].motor_steps_per_rev = g_joint_motor_steps_per_rev[i];
    }
    memcpy(g_robot.T, T_0_6_reset, sizeof(T_0_6_reset));

	g_robot.event_queue = xQueueCreate(ROBOT_MAX_EVENT_NUM, sizeof(struct robot_event));
    if (g_robot.event_queue == NULL) {
      	LOG("create robot event queue failed\n");
      	return; 
  	}

    g_robot.cmd_queue = xQueueCreate(ROBOT_CMD_MAX_NUM, sizeof(struct robot_cmd));
    if (g_robot.cmd_queue == NULL) {
    	LOG("create robot cmd queue failed\n");
    	return;
    }

	/* 鍒涘缓robot鎺у埗浠诲姟(涓荤▼搴? */
  	osThreadAttr_t task_attributes = { .name = "robot_control_task", 
                                     .stack_size = ROBOT_CONTROL_TASK_STACK_SIZE, 
                                     .priority = ROBOT_CONTROL_TASK_PRIORITY};
  	g_robot.control_handle = osThreadNew((osThreadFunc_t)robot_control_task, NULL, &task_attributes);
	if (g_robot.control_handle == NULL) {
		LOG("create robot control task failed\n");
		return;
	}

	/* 鍒涘缓robot cmd 瀛楃涓插鐞嗕换鍔?*/
	task_attributes.name = "robot_cmd_service";
	task_attributes.stack_size = ROBOT_CMD_SERVICE_STACK_SIZE;
	task_attributes.priority = ROBOT_CMD_SERVICE_PRIORITY;
	g_robot.cmd_service_handle = osThreadNew((osThreadFunc_t)robot_cmd_service, NULL, &task_attributes);
	if (g_robot.cmd_service_handle == NULL) {
		LOG("create robot cmd service task failed\n");	
		return;
	}

	// /* 鍒涘缓 robot remote 浠诲姟*/
	// task_attributes.name = "robot_remote_service";
	// task_attributes.stack_size = ROBOT_REMOTE_SERVICE_STACK_SIZE;
	// task_attributes.priority = ROBOT_REMOTE_SERVICE_PRIORITY;
	// g_robot.remote_service_handle = osThreadNew((osThreadFunc_t)robot_remote_service, NULL, &task_attributes);
	// if (g_robot.remote_service_handle == NULL) {
	// 	LOG("create robot remote service task failed\n");	
	// 	return;
	// }
}

static int robot_motion_command_allowed(void)
{
	if (g_robot.event_queue == NULL) {
		return -1;
	}

	if (ROBOT_STATUS_IS(g_robot.status, ROBOT_STATUS_ESTOP)) {
		LOG("[ERROR] robot is in estop, power cycle or clear estop in firmware first\n");
		return 1;
	}

	return 0;
}

int robot_send_joints_sync_event(float *angles)
{
	if (robot_motion_command_allowed() != 0) {
		return -1;	
	}

	struct robot_event event = {0};
	event.type = ROBOT_JOINTS_SYNC_EVENT;
	memcpy(event.param, angles, sizeof(float) * ROBOT_MAX_JOINT_NUM);
	return (int)xQueueSendToBack(g_robot.event_queue, &event, ROBOT_CMD_QUEUE_TIMEOUT);
}

int robot_send_joints_sync_rel_event(float *angles)
{
	if (robot_motion_command_allowed() != 0) {
		return -1;
	}

	struct robot_event event = {0};
	event.type = ROBOT_JOINTS_SYNC_REL_EVENT;
	memcpy(event.param, angles, sizeof(float) * ROBOT_MAX_JOINT_NUM);
	return (int)xQueueSendToBack(g_robot.event_queue, &event, ROBOT_CMD_QUEUE_TIMEOUT);
}

int robot_send_rel_rotate_event(uint8_t joint_id, float angle)
{
	if (robot_motion_command_allowed() != 0) {
		return -1;
	}

	struct robot_event event = {0};
	event.type = ROBOT_JOINT_REL_ROTATE;
	event.joint_id = joint_id;
	event.param[0] = angle;
    return (int)xQueueSendToBack(g_robot.event_queue, &event, ROBOT_CMD_QUEUE_TIMEOUT);
}

int robot_send_remote_event(void)
{
	if (robot_motion_command_allowed() != 0) {
		return -1;
	}

	struct robot_event event = {0};
	event.type = ROBOT_REMOTE_CONTROL_EVENT;
	return (int)xQueueSendToBack(g_robot.event_queue, &event, ROBOT_CMD_QUEUE_TIMEOUT);
}

int robot_send_abs_rotate_event(uint8_t joint_id, float angle)
{
	if (robot_motion_command_allowed() != 0) {
		return -1;
	}

	struct robot_event event = {0};
	event.type = ROBOT_JOINT_ABS_ROTATE;
	event.joint_id = joint_id;
	event.param[0] = angle;
    return (int)xQueueSendToBack(g_robot.event_queue, &event, ROBOT_CMD_QUEUE_TIMEOUT);
}

int robot_send_auto_event(struct position *pos)
{
	if (robot_motion_command_allowed() != 0) {
		return -1;
	}

	struct robot_event event = {0};
	event.type = ROBOT_AUTO_EVENT;
	memcpy(event.param, pos, sizeof(struct position));
	return (int)xQueueSendToBack(g_robot.event_queue, &event, ROBOT_CMD_QUEUE_TIMEOUT);
};

int robot_send_time_func_event(float time_limit_ms)
{
	if (robot_motion_command_allowed() != 0) {
		return -1;
	}

	struct robot_event event = {0};
	event.type = ROBOT_TIMIE_FUNC_EVENT;
	event.param[0] = time_limit_ms;
	return (int)xQueueSendToBack(g_robot.event_queue, &event, ROBOT_CMD_QUEUE_TIMEOUT);
};

int robot_send_reset_event(bool hard_reset)
{
	if (robot_motion_command_allowed() != 0) {
		return -1;
	}

	struct robot_event event = {0};
	if (hard_reset) {
		event.type = ROBOT_HARD_RESET_EVENT;	
	} else {
		event.type = ROBOT_SOFT_RESET_EVENT;
	}
	return (int)xQueueSendToBack(g_robot.event_queue, &event, ROBOT_CMD_QUEUE_TIMEOUT);
}

int robot_send_assist_reset_event(float *param)
{
	if (robot_motion_command_allowed() != 0) {
		return -1;
	}

	struct robot_event event = {0};
	event.type = ROBOT_TEST_EVENT;
	if (param != NULL) {
		memcpy(event.param, param, sizeof(float) * 5);
	}
	return (int)xQueueSendToBack(g_robot.event_queue, &event, ROBOT_CMD_QUEUE_TIMEOUT);
}

int robot_refresh_joint_angle(uint8_t joint_id, float *angle)
{
	if (joint_id >= ROBOT_MAX_JOINT_NUM) {
		return 1;
	}

	if (robot_update_current_angle(joint_id) != 0) {
		return 1;
	}

	if (angle != NULL) {
		*angle = g_robot.joints[joint_id].current_angle;
	}
	return 0;
}

int robot_driver_home(uint8_t joint_id, uint8_t mode)
{
	if ((joint_id >= ROBOT_MAX_JOINT_NUM) || (mode > 3)) {
		return 1;
	}

	Emm_V5_Origin_Trigger_Return(joint_id + 1, mode, false);
	return 0;
}

int robot_driver_enable(uint8_t joint_id, bool enable)
{
	if (joint_id >= ROBOT_MAX_JOINT_NUM) {
		return 1;
	}

	Emm_V5_En_Control(joint_id + 1, enable, false);
	return 0;
}

int robot_driver_enable_all(bool enable)
{
	for (uint8_t i = 0; i < ROBOT_MAX_JOINT_NUM; i++) {
		Emm_V5_En_Control(i + 1, enable, false);
		vTaskDelay(ROBOT_CAN_DELAY);
	}

	return 0;
}

int robot_emergency_stop(bool disable_driver)
{
	ROBOT_STATUS_SET(g_robot.status, ROBOT_STATUS_ESTOP);

	if (g_robot.event_queue != NULL) {
		xQueueReset(g_robot.event_queue);
	}

	for (uint8_t i = 0; i < ROBOT_MAX_JOINT_NUM; i++) {
		robot_joint_stop(i);
		vTaskDelay(ROBOT_CAN_DELAY);
	}

	if (disable_driver) {
		robot_driver_enable_all(false);
	}

	LOG("robot emergency stop, disable_driver:%d\n", disable_driver ? 1 : 0);
	return 0;
}

int robot_resume_from_estop(void)
{
	ROBOT_STATUS_CLEAR(g_robot.status, ROBOT_STATUS_ESTOP);
	LOG("robot estop cleared\n");
	return 0;
}

void robot_set_power_on_auto_reset_enable(bool enable)
{
	g_robot_power_on_auto_reset_enable = enable;
	LOG("robot power-on auto reset %s\n", enable ? "enabled" : "disabled");
}

bool robot_get_power_on_auto_reset_enable(void)
{
	return g_robot_power_on_auto_reset_enable;
}

int robot_teach_point_save(uint8_t slot)
{
	if (slot >= ROBOT_TEACH_POINT_MAX_NUM) {
		return 1;
	}

	for (uint8_t i = 0U; i < ROBOT_MAX_JOINT_NUM; i++) {
		float angle = 0.0f;
		if (robot_refresh_joint_angle(i, &angle) != 0) {
			LOG("teach save failed, joint[%u] read failed\n", i);
			return 1;
		}
		g_robot_teach_points[slot][i] = angle;
	}

	g_robot_teach_valid[slot] = true;
	LOG("teach point %u saved:", (unsigned)(slot + 1U));
	for (uint8_t i = 0U; i < ROBOT_MAX_JOINT_NUM; i++) {
		LOG(" %.2f", g_robot_teach_points[slot][i]);
	}
	LOG("\n");
	return 0;
}

int robot_teach_point_run(uint8_t slot)
{
	if ((slot >= ROBOT_TEACH_POINT_MAX_NUM) || !g_robot_teach_valid[slot]) {
		return 1;
	}

	LOG("teach point %u run\n", (unsigned)(slot + 1U));
	return robot_send_joints_sync_event(g_robot_teach_points[slot]);
}

int robot_teach_point_print(int slot)
{
	if (slot < 0) {
		for (int i = 0; i < ROBOT_TEACH_POINT_MAX_NUM; i++) {
			if (!g_robot_teach_valid[i]) {
				LOG("teach point %d: empty\n", i + 1);
				continue;
			}
			LOG("teach point %d:", i + 1);
			for (uint8_t j = 0U; j < ROBOT_MAX_JOINT_NUM; j++) {
				LOG(" %.2f", g_robot_teach_points[i][j]);
			}
			LOG("\n");
		}
		return 0;
	}

	if ((slot >= ROBOT_TEACH_POINT_MAX_NUM) || !g_robot_teach_valid[slot]) {
		return 1;
	}

	LOG("teach point %d:", slot + 1);
	for (uint8_t j = 0U; j < ROBOT_MAX_JOINT_NUM; j++) {
		LOG(" %.2f", g_robot_teach_points[slot][j]);
	}
	LOG("\n");
	return 0;
}

int robot_driver_clear_clog(uint8_t joint_id)
{
	if (joint_id >= ROBOT_MAX_JOINT_NUM) {
		return 1;
	}

	Emm_V5_Reset_Clog_Pro(joint_id + 1);
	return 0;
}

int robot_driver_set_mode(uint8_t joint_id, uint8_t ctrl_mode)
{
	if ((joint_id >= ROBOT_MAX_JOINT_NUM) || (ctrl_mode > 3)) {
		return 1;
	}

	Emm_V5_Modify_Ctrl_Mode(joint_id + 1, false, ctrl_mode);
	return 0;
}

int robot_read_driver_param(uint8_t joint_id, uint8_t param, uint8_t *data, uint8_t *dlc)
{
	uint32_t start_tick;
	uint8_t id;

	if ((joint_id >= ROBOT_MAX_JOINT_NUM) || (data == NULL) || (dlc == NULL)) {
		return 1;
	}

	vTaskSuspendAll();
	can.rxFrameFlag = false;
	start_tick = HAL_GetTick();
	while(!can.rxFrameFlag) {
		if ((HAL_GetTick() - start_tick) > ROBOT_CAN_TIMEOUT) {
			xTaskResumeAll();
			return 1;
		}
		Emm_V5_Read_Sys_Params(joint_id + 1, (SysParams_t)param);
		HAL_Delay(1);
	}

	taskENTER_CRITICAL();
	xTaskResumeAll();
	id = (uint8_t)(can.CAN_RxMsg.ExtId >> 8) - 1;
	if (id != joint_id) {
		taskEXIT_CRITICAL();
		return 1;
	}

	*dlc = (uint8_t)can.CAN_RxMsg.DLC;
	memcpy(data, (const void *)can.rxData, *dlc);
	taskEXIT_CRITICAL();
	return 0;
}

void robot_print_state(void)
{
	LOG("robot status:0x%08lx\n", (unsigned long)g_robot.status);
	for (int i = 0; i < ROBOT_MAX_JOINT_NUM; i++) {
		int ret = robot_refresh_joint_angle(i, NULL);
		if (ret != 0) {
			LOG("joint[%d] angle read failed, status:0x%08lx\n", i,
				(unsigned long)g_robot.joints[i].status);
			continue;
		}

		LOG("joint[%d] angle:%.2f status:0x%08lx vel:%.2f\n", i,
			g_robot.joints[i].current_angle,
			(unsigned long)g_robot.joints[i].status,
			g_robot.joints[i].velocity);
	}
}

void robot_print_can_diag(void)
{
	uint32_t esr = hcan1.Instance->ESR;
	uint32_t msr = hcan1.Instance->MSR;
	uint32_t tsr = hcan1.Instance->TSR;
	uint32_t tec = (esr >> 16) & 0xFF;
	uint32_t rec = (esr >> 24) & 0xFF;

	LOG("can diag: ErrorCode=0x%08lx ESR=0x%08lx MSR=0x%08lx TSR=0x%08lx TEC=%lu REC=%lu rxFlag=%d\n",
		(unsigned long)hcan1.ErrorCode,
		(unsigned long)esr,
		(unsigned long)msr,
		(unsigned long)tsr,
		(unsigned long)tec,
		(unsigned long)rec,
		can.rxFrameFlag ? 1 : 0);
}

void robot_cmd_send_from_isr(volatile char *cmd, enum cmd_type type)
{
	if (g_robot.cmd_queue == NULL) {
		return;	
	}

	struct robot_cmd robot_cmd = {0};
	robot_cmd.type = type;
	const char *cmd_str = (const char *)cmd;
	int len = strlen(cmd_str);
	strncpy(robot_cmd.cmd, cmd_str, (len >= ROBOT_CMD_LENGTH) ? ROBOT_CMD_LENGTH - 1 : len);
	BaseType_t xHigherPriorityTaskWoken;
    xQueueSendToBackFromISR(g_robot.cmd_queue, &robot_cmd, &xHigherPriorityTaskWoken);
}

static int robot_joint_pin2id(uint16_t pin)
{
    for (int i = 0; i < ROBOT_MAX_JOINT_NUM; i++) {
        if (g_robot.joints[i].limit_gpio_pin == pin) {
            return i;
        }	
    }
    return -1;
}

void HAL_GPIO_EXTI_Callback(uint16_t GPIO_Pin)
{
    uint32_t joint_id = robot_joint_pin2id(GPIO_Pin);
    if ((joint_id >= ROBOT_MAX_JOINT_NUM) || (!g_joint_has_limit_switch[joint_id])) {
        __HAL_GPIO_EXTI_CLEAR_IT(GPIO_Pin);
        return;
    }
    robot_joint_limit_happend(joint_id);
    LOG_FROM_ISR("joint limit switch happened, joint id: %d\n", joint_id);
   __HAL_GPIO_EXTI_CLEAR_IT(GPIO_Pin); // 娓呴櫎涓柇鏍囧織浣? 鍑忓皯鎸夐敭鎶栧姩瀵艰嚧鐨勮瑙﹀彂
}

static int robot_mqtt_joints_sync(void)
{
#if defined(ROBOT_MQTT_ENABLE) && (ROBOT_MQTT_ENABLE == 1)
	char msg[256] = {0};
	snprintf(msg, sizeof(msg), "[PC][%d][%.2f %.2f %.2f %.2f %.2f %.2f]", ROBOT_JOINTS_SYNC_EVENT,
				g_robot.joints[0].current_angle, g_robot.joints[1].current_angle,
				g_robot.joints[2].current_angle, g_robot.joints[3].current_angle,
				g_robot.joints[4].current_angle, g_robot.joints[5].current_angle);
	return esp8266_publish_message(MQTT_TOPIC, msg, 0, 0);
#else
	return 0;
#endif
}

#if defined(ROBOT_MQTT_ENABLE) && (ROBOT_MQTT_ENABLE == 1)
//static void robot_mqtt_sync_task(void)
//{
//	vTaskDelay(1000); // 绛夊緟esp8266鍒濆鍖栧畬鎴?
//
//	while (1) {
//		for (int i = 0; i < ROBOT_MAX_JOINT_NUM; i++) {
//			robot_update_current_angle(i); // 鏇存柊褰撳墠瑙掑害
//		}
//
//		int ret = robot_mqtt_joints_sync();
//		if (ret == 0) {
//			LOG("robot mqtt sync failed, ret:%d\n", ret);
//		}
//		vTaskDelay(ROBOT_MQTT_SYNC_TIME);
//	}
//}

//static int robot_mqtt_sync_task_init(void)
//{
//	// 鍒涘缓浣庝紭鍏堢骇浠诲姟锛屽畾鏈熷線MQTT鏈嶅姟鍣ㄥ悓姝ュ叧鑺傝搴?
//  	osThreadAttr_t task_attributes = { .name = "robot_mqtt_sync_task",
//                                     .stack_size = ROBOT_MQTT_SYNC_TASK_STACK_SIZE,
//                                     .priority = ROBOT_MQTT_SYNC_TASK_PRIORITY};
//  	g_robot.mqtt_sync_task_handle = osThreadNew((osThreadFunc_t)robot_mqtt_sync_task, NULL, &task_attributes);
//	if (g_robot.mqtt_sync_task_handle == NULL) {
//		LOG("create robot mqtt sync task failed\n");
//		return -1;
//	}
//	return 0;
//}
#endif	// defined(ROBOT_MQTT_ENABLE) && (ROBOT_MQTT_ENABLE == 1)

void robot_cmd_service(void)
{
	struct robot_cmd rb_cmd = {0};

#if defined(ROBOT_MQTT_ENABLE) &&  (ROBOT_MQTT_ENABLE == 1)
	int ret;
	LOG("robot mqtt service init...    \n");
	HAL_Delay(1000);	// 绛夊緟esp8266鍒濆鍖栧畬鎴?
    ret = esp8266_mqtt_init();
	if (!ret) {
		LOG("robot mqtt service init failed\n");
		return;	
	}

	// ret = robot_mqtt_sync_task_init();
	// if (ret != 0) {
	// 	LOG("robot mqtt sync task init failed\n");
	// 	return;	
	// }

	LOG("robot mqtt service init successed\n");
#endif

	while(xQueueReceive(g_robot.cmd_queue, &rb_cmd, portMAX_DELAY) == pdPASS) {
		switch (rb_cmd.type)
		{
			case CMD_TYPE_UART1:
				robot_uart1_handle(&rb_cmd);
				break;
			
			case CMD_TYPE_MQTT:
				robot_mqtt_handle(&rb_cmd);
				break;
			
			default:
				break;
		}
	}
}

/**
 * @brief 瀵规満姊拌噦杩愬姩璺緞杩涜绾挎€ф彃鍊笺€?
 * 
 * 璇ュ嚱鏁版牴鎹洰鏍囦綅缃拰褰撳墠浣嶇疆锛岃绠楀嚭鏈烘鑷傝繍鍔ㄨ矾寰勪笂鐨勬彃鍊肩偣銆?
 * 閫氳繃绾挎€ф彃鍊肩殑鏂瑰紡锛屽皢浠庡綋鍓嶄綅缃埌鐩爣浣嶇疆鐨勮矾寰勫垝鍒嗕负澶氫釜鐐癸紝
 * 浠ュ疄鐜版満姊拌噦鐨勫钩婊戣繍鍔ㄣ€?
 * 
 * @param target 鎸囧悜鐩爣浣嶇疆缁撴瀯浣撶殑鎸囬拡锛屽寘鍚洰鏍囦綅缃殑x銆亂銆亃鍧愭爣銆?
 * @param size 鎸囧悜鏁存暟鐨勬寚閽堬紝鐢ㄤ簬杩斿洖鎻掑€肩偣鐨勬暟閲忋€?
 * @return struct position* 鎸囧悜鍖呭惈鎻掑€肩偣鐨勪綅缃粨鏋勪綋鏁扮粍鐨勬寚閽堬紝
 *         鑻ュ唴瀛樺垎閰嶅け璐ュ垯杩斿洖NULL銆?
 */
static struct position *robot_path_interpolation_linear(struct position *target, int *size)
{
    float dx = target->x - g_robot.cur_pos.x;
    float dy = target->y - g_robot.cur_pos.y;
    float dz = target->z - g_robot.cur_pos.z;
    double distance = sqrt(dx * dx + dy * dy + dz * dz);

    int numPoints = (int)(ceil(distance / ROBOT_INTERPOLATION_RESOLUTION)) + 1; // 鍔?鏄洜涓哄寘鎷捣鐐瑰拰缁堢偣
    if (numPoints < 2) {
        numPoints = 2;
    }
    if (numPoints > ROBOT_AUTO_PATH_MAX_POINTS) {
        LOG("robot auto path truncated, points:%d max:%d\n", numPoints, ROBOT_AUTO_PATH_MAX_POINTS);
        numPoints = ROBOT_AUTO_PATH_MAX_POINTS;
    }
    *size = numPoints;

    struct position* path = g_auto_path_buf;

    // 璁＄畻姣忎竴姝ョ殑澧為噺
    double step_x = dx / (numPoints - 1);
    double step_y = dy / (numPoints - 1);
    double step_z = dz / (numPoints - 1);

    // 鎻掑€艰绠楁瘡涓偣鐨勫潗鏍?
    for (int i = 0; i < numPoints; i++) {
        path[i].x = g_robot.cur_pos.x + i * step_x;
        path[i].y = g_robot.cur_pos.y + i * step_y;
        path[i].z = g_robot.cur_pos.z + i * step_z;
    }

    return path;
}

static int robot_update_current_angle(uint8_t joint_id)
{
	struct joint *joint = &g_robot.joints[joint_id];
	vTaskSuspendAll();
	can.rxFrameFlag = false;
	uint32_t start_tick = HAL_GetTick();
	while(!can.rxFrameFlag) {
		if ((HAL_GetTick() - start_tick) > ROBOT_CAN_TIMEOUT) {
			LOG("joint %u update current angle timeout.\n", joint_id);
			xTaskResumeAll();
			return 1;
		}
		Emm_V5_Read_Sys_Params(joint_id + 1, S_CPOS);
		HAL_Delay(1);
	}
	
	taskENTER_CRITICAL();
	xTaskResumeAll();
	uint8_t id = (uint8_t)(can.CAN_RxMsg.ExtId >> 8) - 1;
	if ((can.rxData[0] != 0x36) || (can.rxData[6] != 0x6b) || (id != joint_id)) { // 璇诲彇澶辫触
		taskEXIT_CRITICAL();
		return 1;
	}

	float angle = 0;
	for (int i = 5; i >= 2; i--) {
		angle += (float)(((uint32_t)can.rxData[i]) << ((5 - i) << 3));
	}

	if (can.rxData[1] == 0x01) { // 璐熸暟
		angle = -angle;
	}

	// 淇涓哄叧鑺傛柟鍚?
	if (joint->postive_direction == MOTOR_DIR_CCW) { // 淇涓烘鏂瑰悜
		angle = -angle;
	}
	
	taskEXIT_CRITICAL();
	// 杞崲涓哄姬搴?
	angle = angle * 360 / 65536 / joint->reduction_ratio + g_joints_init[joint_id].current_angle;
	joint->current_angle = robot_angle_normalize(angle);
	return 0;
}

static void robot_joint_stop(uint8_t joint_id)
{
	vTaskSuspendAll();
	can.rxFrameFlag = false;
	uint32_t start_tick = HAL_GetTick();
	while(!can.rxFrameFlag) {
		if ((HAL_GetTick() - start_tick) > ROBOT_CAN_TIMEOUT) {
			LOG("joint %u stop timeout.\n", joint_id);
			xTaskResumeAll();
			return;
		}
		Emm_V5_Stop_Now(joint_id + 1, false);
		HAL_Delay(1);
	}
	xTaskResumeAll();
	g_robot.joints[joint_id].velocity = 0;
	return;
}

static void robot_joint_stop_quick(uint8_t joint_id)
{
	for (uint8_t i = 0U; i < 3U; i++) {
		Emm_V5_Stop_Now(joint_id + 1, false);
		vTaskDelay(ROBOT_CAN_DELAY);
	}
	g_robot.joints[joint_id].velocity = 0.0f;
}

static void robot_joint_stop_from_isr(uint8_t joint_id)
{
	Emm_V5_Stop_Now(joint_id + 1, false);
	g_robot.joints[joint_id].velocity = 0;
}

static int time_func_circle(uint32_t time_ms, struct position *pos)
{
	float angle_vel = 2 * M_PI / 10; // 瑙掗€熷害, 10s涓€涓懆鏈?
	float r = 30;
	float first_x = 10;
	
	if (time_ms < 1000) {	// 鍓?S绉诲姩10mm
		pos->x = 0;
		pos->z = 0;
		pos->y = (-first_x) * time_ms / 1000;
		return 0;
	}
	
	pos->z = 0;	// 鍥哄畾楂樺害
	time_ms -= 1000;
	// 鍗婂緞涓?0mm
	pos->x = r * sin(angle_vel * time_ms / 1000);
	pos->y = (r * cos(angle_vel * time_ms / 1000) - r - first_x);
	return 0;
}

