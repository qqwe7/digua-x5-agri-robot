#include "dht11_app.h"

#include <string.h>

#define DHT11_START_LOW_MS         20U
#define DHT11_START_RELEASE_US     30U
#define DHT11_ACK_TIMEOUT_US       120U
#define DHT11_BIT_START_TIMEOUT_US 80U
#define DHT11_BIT_END_TIMEOUT_US   120U
#define DHT11_BIT_SAMPLE_US        40U

static uint8_t g_dwt_ready = 0U;
static uint32_t g_cycles_per_us = 1U;

static void DHT11_DwtInit(void)
{
  if (g_dwt_ready != 0U)
  {
    return;
  }

  CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
  DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
  DWT->CYCCNT = 0U;

  g_cycles_per_us = HAL_RCC_GetHCLKFreq() / 1000000U;
  if (g_cycles_per_us == 0U)
  {
    g_cycles_per_us = 1U;
  }

  g_dwt_ready = 1U;
}

static void DHT11_DelayUs(uint32_t delay_us)
{
  uint32_t start_tick;
  uint32_t target_cycles;

  DHT11_DwtInit();

  start_tick = DWT->CYCCNT;
  target_cycles = delay_us * g_cycles_per_us;
  while ((DWT->CYCCNT - start_tick) < target_cycles)
  {
  }
}

static void DHT11_SetPinOutput(DHT11_t *dht11)
{
  GPIO_InitTypeDef gpio_init = {0};

  gpio_init.Pin = dht11->gpio_pin;
  gpio_init.Mode = GPIO_MODE_OUTPUT_OD;
  gpio_init.Pull = GPIO_PULLUP;
  gpio_init.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(dht11->gpio_port, &gpio_init);
}

static void DHT11_SetPinInput(DHT11_t *dht11)
{
  GPIO_InitTypeDef gpio_init = {0};

  gpio_init.Pin = dht11->gpio_pin;
  gpio_init.Mode = GPIO_MODE_INPUT;
  gpio_init.Pull = GPIO_PULLUP;
  HAL_GPIO_Init(dht11->gpio_port, &gpio_init);
}

static int8_t DHT11_WaitForState(DHT11_t *dht11, GPIO_PinState target_state, uint32_t timeout_us)
{
  uint32_t start_tick;
  uint32_t timeout_cycles;

  DHT11_DwtInit();

  start_tick = DWT->CYCCNT;
  timeout_cycles = timeout_us * g_cycles_per_us;
  while (HAL_GPIO_ReadPin(dht11->gpio_port, dht11->gpio_pin) != target_state)
  {
    if ((DWT->CYCCNT - start_tick) > timeout_cycles)
    {
      return -1;
    }
  }

  return 0;
}

int8_t DHT11_Create(DHT11_t *dht11, GPIO_TypeDef *gpio_port, uint16_t gpio_pin)
{
  if ((dht11 == NULL) || (gpio_port == NULL))
  {
    return -1;
  }

  memset(dht11, 0, sizeof(*dht11));
  dht11->gpio_port = gpio_port;
  dht11->gpio_pin = gpio_pin;
  dht11->last_error = 0;
  DHT11_SetPinInput(dht11);
  return 0;
}

int8_t DHT11_Read(DHT11_t *dht11)
{
  uint8_t raw_data[5] = {0};
  uint8_t i;
  uint8_t checksum;

  if (dht11 == NULL)
  {
    return -1;
  }

  DHT11_SetPinOutput(dht11);
  HAL_GPIO_WritePin(dht11->gpio_port, dht11->gpio_pin, GPIO_PIN_RESET);
  HAL_Delay(DHT11_START_LOW_MS);
  HAL_GPIO_WritePin(dht11->gpio_port, dht11->gpio_pin, GPIO_PIN_SET);
  DHT11_DelayUs(DHT11_START_RELEASE_US);
  DHT11_SetPinInput(dht11);

  if (DHT11_WaitForState(dht11, GPIO_PIN_RESET, DHT11_ACK_TIMEOUT_US) != 0)
  {
    dht11->last_error = -2;
    return -2;
  }

  if (DHT11_WaitForState(dht11, GPIO_PIN_SET, DHT11_ACK_TIMEOUT_US) != 0)
  {
    dht11->last_error = -3;
    return -3;
  }

  if (DHT11_WaitForState(dht11, GPIO_PIN_RESET, DHT11_ACK_TIMEOUT_US) != 0)
  {
    dht11->last_error = -4;
    return -4;
  }

  for (i = 0U; i < 40U; i++)
  {
    raw_data[i / 8U] <<= 1U;

    if (DHT11_WaitForState(dht11, GPIO_PIN_SET, DHT11_BIT_START_TIMEOUT_US) != 0)
    {
      dht11->last_error = -5;
      return -5;
    }

    DHT11_DelayUs(DHT11_BIT_SAMPLE_US);
    if (HAL_GPIO_ReadPin(dht11->gpio_port, dht11->gpio_pin) == GPIO_PIN_SET)
    {
      raw_data[i / 8U] |= 0x01U;
    }

    if (DHT11_WaitForState(dht11, GPIO_PIN_RESET, DHT11_BIT_END_TIMEOUT_US) != 0)
    {
      dht11->last_error = -6;
      return -6;
    }
  }

  checksum = (uint8_t)(raw_data[0] + raw_data[1] + raw_data[2] + raw_data[3]);
  if (checksum != raw_data[4])
  {
    dht11->last_error = -7;
    return -7;
  }

  dht11->data.humidity = raw_data[0] + (raw_data[1] * 0.1f);
  dht11->data.temperature = raw_data[2] + (raw_data[3] * 0.1f);
  dht11->data.timestamp = HAL_GetTick();
  dht11->data.data_valid = 1U;
  dht11->last_error = 0;
  return 0;
}

DHT11_Data_t *DHT11_GetData(DHT11_t *dht11)
{
  if (dht11 == NULL)
  {
    return NULL;
  }

  return &dht11->data;
}
