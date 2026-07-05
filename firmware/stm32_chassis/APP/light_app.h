#ifndef __LIGHT_APP_H__
#define __LIGHT_APP_H__

#include "main.h"

typedef struct
{
  uint16_t raw;
  float level_percent;
  uint32_t timestamp;
  uint8_t data_valid;
} Light_Data_t;

typedef struct
{
  uint8_t initialized;
  Light_Data_t data;
} Light_t;

int8_t Light_Create(Light_t *light);
int8_t Light_Read(Light_t *light);
Light_Data_t *Light_GetData(Light_t *light);

#endif
