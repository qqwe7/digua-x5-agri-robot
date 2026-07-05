#include "light_app.h"

#define LIGHT_ADC_TIMEOUT_LOOPS 200000U

static void Light_AdcGpioInit(void)
{
  GPIO_InitTypeDef gpio_init = {0};

  __HAL_RCC_GPIOA_CLK_ENABLE();
  gpio_init.Pin = LIGHT_ADC_Pin;
  gpio_init.Mode = GPIO_MODE_ANALOG;
  gpio_init.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(LIGHT_ADC_GPIO_Port, &gpio_init);
}

static void Light_AdcInit(void)
{
  __HAL_RCC_ADC1_CLK_ENABLE();

  ADC->CCR = 0U;
  ADC1->CR1 = 0U;
  ADC1->CR2 = ADC_CR2_ADON;
  ADC1->SMPR1 = 0U;
  ADC1->SMPR2 = (7U << ADC_SMPR2_SMP0_Pos);
  ADC1->SQR1 = 0U;
  ADC1->SQR2 = 0U;
  ADC1->SQR3 = 0U;
  HAL_Delay(1);
}

static uint16_t Light_AdcReadRaw(void)
{
  uint32_t timeout = LIGHT_ADC_TIMEOUT_LOOPS;

  ADC1->SR = 0U;
  ADC1->CR2 |= ADC_CR2_SWSTART;
  while (((ADC1->SR & ADC_SR_EOC) == 0U) && (timeout > 0U))
  {
    timeout--;
  }

  if (timeout == 0U)
  {
    return 0U;
  }

  return (uint16_t)(ADC1->DR & 0x0FFFU);
}

int8_t Light_Create(Light_t *light)
{
  if (light == NULL)
  {
    return -1;
  }

  light->initialized = 0U;
  light->data.raw = 0U;
  light->data.level_percent = 0.0f;
  light->data.timestamp = 0U;
  light->data.data_valid = 0U;

  Light_AdcGpioInit();
  Light_AdcInit();
  light->initialized = 1U;
  return 0;
}

int8_t Light_Read(Light_t *light)
{
  uint16_t raw;

  if ((light == NULL) || (light->initialized == 0U))
  {
    return -1;
  }

  raw = Light_AdcReadRaw();
  light->data.raw = raw;
  light->data.level_percent = ((float)raw * 100.0f) / 4095.0f;
  light->data.timestamp = HAL_GetTick();
  light->data.data_valid = 1U;
  return 0;
}

Light_Data_t *Light_GetData(Light_t *light)
{
  if (light == NULL)
  {
    return NULL;
  }

  return &light->data;
}
