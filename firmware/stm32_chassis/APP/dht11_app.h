#ifndef __DHT11_APP_H__
#define __DHT11_APP_H__

#include "main.h"

typedef struct
{
  float humidity;
  float temperature;
  uint32_t timestamp;
  uint8_t data_valid;
} DHT11_Data_t;

typedef struct
{
  GPIO_TypeDef *gpio_port;
  uint16_t gpio_pin;
  int8_t last_error;
  DHT11_Data_t data;
} DHT11_t;

int8_t DHT11_Create(DHT11_t *dht11, GPIO_TypeDef *gpio_port, uint16_t gpio_pin);
int8_t DHT11_Read(DHT11_t *dht11);
DHT11_Data_t *DHT11_GetData(DHT11_t *dht11);

#endif
