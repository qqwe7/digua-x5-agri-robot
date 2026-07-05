#include "robot.h"
#include "usart.h"
#include "string.h"
#include <stdio.h>
#include "robot_cmd.h"
#include "Emm_V5.h"

static int robot_soft_reset_handle(float *param);
static int robot_rel_rotate_handle(float *param);
static int robot_auto_handle(float *param);
static int robot_abs_rotate_handle(float *param);
static int robot_drv_home_handle(float *param);
static int robot_read_pos_handle(float *param);
static int robot_state_handle(float *param);
static int robot_can_diag_handle(float *param);
static int robot_drv_enable_handle(float *param);
static int robot_drv_enable_all_handle(float *param);
static int robot_drv_unclog_handle(float *param);
static int robot_drv_mode_handle(float *param);
static int robot_drv_flag_handle(float *param);
static int robot_joints_sync_rel_handle(float *param);
static int robot_brake_handle(float *param);
static int robot_resume_handle(float *param);
static int robot_assist_reset_handle(float *param);
static int robot_teach_save_handle(float *param);
static int robot_teach_run_handle(float *param);
static int robot_teach_show_handle(float *param);

void robot_mqtt_handle(struct robot_cmd *cmd)
{
	float param[6] = {0};
	int strlen = 0;
	int type = 0;
	
	LOG("robot mqtt cmd: %s\n", cmd->cmd);

	// [MCU][TYPE][ARG0-5]
	int result = sscanf(cmd->cmd, "+MQTTSUBRECV:0,\"arm/change\",%d,[MCU][%d][%f %f %f %f %f %f]", &strlen, &type,
			&param[0], &param[1], &param[2],
			&param[3], &param[4], &param[5]);
	
	if (result < 8) { // 解析失败
		return;
	}
	
	switch (type)
	{
		case ROBOT_JOINT_ABS_ROTATE:
			robot_abs_rotate_handle(param);
			break;
		
		case ROBOT_AUTO_EVENT:
			robot_auto_handle(param);
			break;
		
		case ROBOT_JOINTS_SYNC_EVENT:
			robot_auto_handle(param);
			break;
		
		default:
			break;
	}
}

static int robot_remote_enable_handle(float *param)
{
	robot_soft_reset_handle(param);	/* 复位 */
	ROBOT_STATUS_SET(g_robot.status, ROBOT_STATUS_RMODE_ENABLE);
	return robot_send_remote_event();
}

static int robot_remote_disable_handle(float *param)
{
	(void)param;
	ROBOT_STATUS_CLEAR(g_robot.status, ROBOT_STATUS_RMODE_ENABLE);
	robot_soft_reset_handle(param);	/* 复位 */
	return pdPASS;	
}

static int robot_rel_rotate_handle(float *param)
{
	uint32_t joint_id = (uint32_t)param[0];
	return robot_send_rel_rotate_event(joint_id, param[1]);
}

static int robot_abs_rotate_handle(float *param)
{
	uint32_t joint_id = (uint32_t)param[0];
	return robot_send_abs_rotate_event(joint_id, param[1]);
}

static int robot_auto_handle(float *param)
{
	return robot_send_auto_event((struct position *)param);
}

static int robot_joints_sync_handle(float *param)
{
	return robot_send_joints_sync_event(param);
}

static int robot_joints_sync_rel_handle(float *param)
{
	return robot_send_joints_sync_rel_event(param);
}

static int robot_hard_reset_handle(float *param)
{
	(void)param;
	return robot_send_reset_event(true);	
}

static int robot_soft_reset_handle(float *param)
{
	(void)param;
	return robot_send_reset_event(false);	
}

static int robot_time_func_handle(float *param)
{
	return robot_send_time_func_event(param[0] * 1000);
}

static int robot_remote_event_handle(float *param)
{
	if (!ROBOT_STATUS_IS(g_robot.status, ROBOT_STATUS_RMODE_ENABLE)) {
		return pdPASS;
	}

	float vx = -param[0] * ROBOT_REMOTE_MAX_VELOCITY;
	float vy = param[1] * ROBOT_REMOTE_MAX_VELOCITY;
	float vz = (param[4] - param[5]) / 2 * ROBOT_REMOTE_MAX_VELOCITY;
	float rx = -param[3] * ROBOT_REMOTE_MAX_RPM;
	float ry = param[2] * ROBOT_REMOTE_MAX_RPM;
	
	taskENTER_CRITICAL();
	g_remote_control.vx = vx;
	g_remote_control.vy = vy;
	g_remote_control.vz = vz;
	g_remote_control.rx = rx;
	g_remote_control.ry = ry;
	taskEXIT_CRITICAL();

	return pdPASS;
}

static int robot_zero_handle(float *param)
{
	(void)param;
	LOG("robot reset zero.\n");
	for (int i = 0; i < ROBOT_MAX_JOINT_NUM; i++) {
		Emm_V5_Reset_CurPos_To_Zero(i + 1);
		vTaskDelay(10);
	}
	return pdPASS;
}

static int robot_drv_home_handle(float *param)
{
	uint32_t joint_id = (uint32_t)param[0];
	uint32_t mode = (uint32_t)param[1];
	int ret;

	if ((joint_id >= ROBOT_MAX_JOINT_NUM) || (mode > 3)) {
		return 1;
	}

	LOG("driver home trigger, joint:%lu mode:%lu\n",
		(unsigned long)joint_id, (unsigned long)mode);
	ret = robot_driver_home((uint8_t)joint_id, (uint8_t)mode);
	return (ret == 0) ? pdPASS : 1;
}

static int robot_read_pos_handle(float *param)
{
	uint32_t joint_id = (uint32_t)param[0];
	float angle = 0;

	if (joint_id >= ROBOT_MAX_JOINT_NUM) {
		return 1;
	}

	if (robot_refresh_joint_angle((uint8_t)joint_id, &angle) != 0) {
		LOG("joint[%lu] read pos failed\n", (unsigned long)joint_id);
		return 1;
	}

	LOG("joint[%lu] angle:%.2f\n", (unsigned long)joint_id, angle);
	return pdPASS;
}

static int robot_state_handle(float *param)
{
	(void)param;
	robot_print_state();
	return pdPASS;
}

static int robot_can_diag_handle(float *param)
{
	(void)param;
	robot_print_can_diag();
	return pdPASS;
}

static int robot_drv_enable_handle(float *param)
{
	uint32_t joint_id = (uint32_t)param[0];
	uint32_t enable = (uint32_t)param[1];
	int ret;

	if ((joint_id >= ROBOT_MAX_JOINT_NUM) || (enable > 1)) {
		return 1;
	}

	LOG("driver enable, joint:%lu enable:%lu\n",
		(unsigned long)joint_id, (unsigned long)enable);
	ret = robot_driver_enable((uint8_t)joint_id, (bool)enable);
	return (ret == 0) ? pdPASS : 1;
}

static int robot_drv_enable_all_handle(float *param)
{
	uint32_t enable = (uint32_t)param[0];

	if (enable > 1U) {
		return 1;
	}

	LOG("driver enable all: %lu\n", (unsigned long)enable);
	return (robot_driver_enable_all((bool)enable) == 0) ? pdPASS : 1;
}

static int robot_drv_unclog_handle(float *param)
{
	uint32_t joint_id = (uint32_t)param[0];
	int ret;

	if (joint_id >= ROBOT_MAX_JOINT_NUM) {
		return 1;
	}

	LOG("driver clear clog, joint:%lu\n", (unsigned long)joint_id);
	ret = robot_driver_clear_clog((uint8_t)joint_id);
	return (ret == 0) ? pdPASS : 1;
}

static int robot_drv_mode_handle(float *param)
{
	uint32_t joint_id = (uint32_t)param[0];
	uint32_t mode = (uint32_t)param[1];
	int ret;

	if ((joint_id >= ROBOT_MAX_JOINT_NUM) || (mode > 3)) {
		return 1;
	}

	LOG("driver mode, joint:%lu mode:%lu\n",
		(unsigned long)joint_id, (unsigned long)mode);
	ret = robot_driver_set_mode((uint8_t)joint_id, (uint8_t)mode);
	return (ret == 0) ? pdPASS : 1;
}

static int robot_drv_flag_handle(float *param)
{
	uint32_t joint_id = (uint32_t)param[0];
	uint8_t data[8] = {0};
	uint8_t dlc = 0;
	int ret;

	if (joint_id >= ROBOT_MAX_JOINT_NUM) {
		return 1;
	}

	ret = robot_read_driver_param((uint8_t)joint_id, S_FLAG, data, &dlc);
	if (ret != 0) {
		LOG("driver flag read failed, joint:%lu\n", (unsigned long)joint_id);
		return 1;
	}

	LOG("driver flag, joint:%lu dlc:%u data:", (unsigned long)joint_id, dlc);
	for (uint8_t i = 0; i < dlc; i++) {
		LOG(" %02x", data[i]);
	}
	LOG("\n");
	return pdPASS;
}

static int robot_brake_handle(float *param)
{
	bool disable_driver = ((uint32_t)param[0] != 0U);
	return (robot_emergency_stop(disable_driver) == 0) ? pdPASS : 1;
}

static int robot_resume_handle(float *param)
{
	(void)param;
	return (robot_resume_from_estop() == 0) ? pdPASS : 1;
}

static int robot_assist_reset_handle(float *param)
{
	return robot_send_assist_reset_event(param);
}

static int robot_teach_save_handle(float *param)
{
	uint32_t slot = (uint32_t)param[0];
	if ((slot == 0U) || (slot > 8U)) {
		return 1;
	}

	return (robot_teach_point_save((uint8_t)(slot - 1U)) == 0) ? pdPASS : 1;
}

static int robot_teach_run_handle(float *param)
{
	uint32_t slot = (uint32_t)param[0];
	if ((slot == 0U) || (slot > 8U)) {
		return 1;
	}

	return (robot_teach_point_run((uint8_t)(slot - 1U)) == 0) ? pdPASS : 1;
}

static int robot_teach_show_handle(float *param)
{
	int slot = (int)param[0];
	if (slot == 0) {
		return (robot_teach_point_print(-1) == 0) ? pdPASS : 1;
	}
	if ((slot < 1) || (slot > 8)) {
		return 1;
	}

	return (robot_teach_point_print(slot - 1) == 0) ? pdPASS : 1;
}

static struct robot_cmd_info robot_uart1_cmd_table[] = {
	{"brake", robot_brake_handle},
	{"rel_rotate", robot_rel_rotate_handle},
	{"abs_rotate", robot_abs_rotate_handle},
	{"hard_reset", robot_hard_reset_handle},
	{"soft_reset", robot_soft_reset_handle},
	{"zero", robot_zero_handle},
	{"state", robot_state_handle},
	{"read_pos", robot_read_pos_handle},
	{"drv_home", robot_drv_home_handle},
	{"drv_enable", robot_drv_enable_handle},
	{"drv_enable_all", robot_drv_enable_all_handle},
	{"drv_unclog", robot_drv_unclog_handle},
	{"drv_mode", robot_drv_mode_handle},
	{"drv_flag", robot_drv_flag_handle},
	{"resume", robot_resume_handle},
	{"assist_reset", robot_assist_reset_handle},
	{"auto", robot_auto_handle},
	// {"time_func", robot_time_func_handle},
	{NULL, NULL},
};

void robot_uart1_handle(struct robot_cmd *rb_cmd)
{
	static char event_type[20] = {0};
	float param[6] = {0};
	char *cmd = rb_cmd->cmd;
	int ret;

	if (strcmp(cmd, "stop reset") == 0) {
		robot_set_power_on_auto_reset_enable(false);
		return;
	}

	if (strcmp(cmd, "start reset") == 0) {
		robot_set_power_on_auto_reset_enable(true);
		return;
	}

	if (sscanf(cmd, "teach save %f", &param[0]) == 1) {
		ret = robot_teach_save_handle(param);
		if (ret != pdPASS) {
			LOG("[ERROR] teach save %.0f\n", param[0]);
		}
		return;
	}

	if (sscanf(cmd, "teach run %f", &param[0]) == 1) {
		ret = robot_teach_run_handle(param);
		if (ret != pdPASS) {
			LOG("[ERROR] teach run %.0f\n", param[0]);
		}
		return;
	}

	if (strcmp(cmd, "teach show") == 0) {
		param[0] = 0.0f;
		ret = robot_teach_show_handle(param);
		if (ret != pdPASS) {
			LOG("[ERROR] teach show\n");
		}
		return;
	}

	if (sscanf(cmd, "teach show %f", &param[0]) == 1) {
		ret = robot_teach_show_handle(param);
		if (ret != pdPASS) {
			LOG("[ERROR] teach show %.0f\n", param[0]);
		}
		return;
	}

	ret = sscanf(cmd, "%19s %f %f %f %f %f %f", event_type, &param[0], &param[1], &param[2], 
		&param[3], &param[4], &param[5]);
	if (ret < 1) { // 解析失败
        LOG("event_type parse error: %s\n", cmd);
        return;
    }

	for (int i = 0; robot_uart1_cmd_table[i].event_type != NULL; i++) {
		if (strcmp(event_type, robot_uart1_cmd_table[i].event_type) == 0) {
			ret = robot_uart1_cmd_table[i].cmd_func(param);
			if (ret != pdPASS) {
				LOG("[ERROR] event_type:%s param:%.2f %.2f %.2f\n",
					event_type, param[0], param[1], param[2]);
				return;
			}
			return;
		}
	}

	LOG("uart cmd parse error: %s\n", cmd);
	return;
}

