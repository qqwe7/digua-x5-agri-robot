#include "scheduler.h"
#include "MyDefine.h"

typedef struct {
  void (*task_func)(void);
  uint32_t rate_ms;
  uint32_t last_run;
} scheduler_task_t;

static void System_Init(void)
{
  Uart_Init();
  CanMotor_Init();
}

static scheduler_task_t scheduler_task[] = {
  {Uart_Task, 10, 0},
  {CanMotor_Task, 5, 0},
};

static uint8_t task_num;

void Scheduler_Init(void)
{
  System_Init();
  task_num = sizeof(scheduler_task) / sizeof(scheduler_task[0]);
}

void Scheduler_Run(void)
{
  for (uint8_t i = 0; i < task_num; i++)
  {
    uint32_t now_time = HAL_GetTick();
    if (now_time >= scheduler_task[i].rate_ms + scheduler_task[i].last_run)
    {
      scheduler_task[i].last_run = now_time;
      scheduler_task[i].task_func();
    }
  }
}
