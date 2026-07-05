#include "hwt101_driver.h"

static int8_t HWT101_ValidateParams(HWT101_t *hwt);
static uint8_t HWT101_CalculateChecksum(uint8_t *data, uint8_t length);
static int8_t HWT101_ParseGyroPacket(HWT101_t *hwt, uint8_t *packet);
static int8_t HWT101_ParseAnglePacket(HWT101_t *hwt, uint8_t *packet);
static float HWT101_ConvertGyroData(uint8_t low, uint8_t high);
static float HWT101_ConvertAngleData(uint8_t low, uint8_t high);
static int8_t HWT101_SendCommand(HWT101_t *hwt, uint8_t reg_addr, uint16_t data);
static int8_t HWT101_UnlockRegister(HWT101_t *hwt);

int8_t HWT101_Create(HWT101_t *hwt, UART_HandleTypeDef *huart, uint32_t timeout_ms)
{
    uint8_t i;

    if ((hwt == NULL) || (huart == NULL))
    {
        return -1;
    }

    if (timeout_ms == 0U)
    {
        timeout_ms = HWT101_TIMEOUT_MS;
    }

    hwt->hw.huart = huart;
    hwt->hw.timeout_ms = timeout_ms;

    hwt->data.roll = 0.0f;
    hwt->data.pitch = 0.0f;
    hwt->data.yaw = 0.0f;
    hwt->data.gyro_z_raw = 0.0f;
    hwt->data.gyro_z = 0.0f;
    hwt->data.version = 0U;
    hwt->data.timestamp = 0U;
    hwt->data.data_valid = 0U;

    hwt->state = HWT101_STATE_IDLE;
    hwt->enable = 1U;
    hwt->rx_index = 0U;

    for (i = 0U; i < HWT101_BUFFER_SIZE; i++)
    {
        hwt->rx_buffer[i] = 0U;
    }

    return 0;
}

int8_t HWT101_ProcessBuffer(HWT101_t *hwt, uint8_t *buffer, uint16_t length)
{
    uint16_t i;

    if ((HWT101_ValidateParams(hwt) != 0) || (buffer == NULL) || (length == 0U))
    {
        return -1;
    }

    if (!hwt->enable)
    {
        return -1;
    }

    for (i = 0U; i < length; i++)
    {
        uint8_t byte = buffer[i];

        switch (hwt->state)
        {
            case HWT101_STATE_IDLE:
                if (byte == HWT101_HEADER)
                {
                    hwt->rx_buffer[0] = byte;
                    hwt->rx_index = 1U;
                    hwt->state = HWT101_STATE_RECEIVING;
                }
                break;

            case HWT101_STATE_RECEIVING:
                hwt->rx_buffer[hwt->rx_index] = byte;
                hwt->rx_index++;

                if (hwt->rx_index >= HWT101_PACKET_SIZE)
                {
                    uint8_t calculated_checksum = HWT101_CalculateChecksum(hwt->rx_buffer, HWT101_PACKET_SIZE - 1U);
                    uint8_t received_checksum = hwt->rx_buffer[HWT101_PACKET_SIZE - 1U];

                    if (calculated_checksum == received_checksum)
                    {
                        uint8_t packet_type = hwt->rx_buffer[1];

                        if (packet_type == HWT101_TYPE_GYRO)
                        {
                            HWT101_ParseGyroPacket(hwt, hwt->rx_buffer);
                        }
                        else if (packet_type == HWT101_TYPE_ANGLE)
                        {
                            HWT101_ParseAnglePacket(hwt, hwt->rx_buffer);
                        }

                        hwt->state = HWT101_STATE_DATA_READY;
                    }
                    else
                    {
                        hwt->state = HWT101_STATE_ERROR;
                    }

                    hwt->rx_index = 0U;

                    if (hwt->state == HWT101_STATE_ERROR)
                    {
                        hwt->state = HWT101_STATE_IDLE;
                    }
                }
                break;

            case HWT101_STATE_DATA_READY:
                hwt->state = HWT101_STATE_IDLE;
                i--;
                break;

            case HWT101_STATE_ERROR:
                hwt->state = HWT101_STATE_IDLE;
                i--;
                break;

            default:
                hwt->state = HWT101_STATE_IDLE;
                break;
        }
    }

    return 0;
}

HWT101_State_t HWT101_GetState(HWT101_t *hwt)
{
    if (HWT101_ValidateParams(hwt) != 0)
    {
        return HWT101_STATE_ERROR;
    }

    return hwt->state;
}

int8_t HWT101_Enable(HWT101_t *hwt, uint8_t enable)
{
    if (HWT101_ValidateParams(hwt) != 0)
    {
        return -1;
    }

    hwt->enable = enable;

    if (!enable)
    {
        hwt->data.roll = 0.0f;
        hwt->data.pitch = 0.0f;
        hwt->data.yaw = 0.0f;
        hwt->data.gyro_z_raw = 0.0f;
        hwt->data.gyro_z = 0.0f;
        hwt->data.version = 0U;
        hwt->data.timestamp = 0U;
        hwt->data.data_valid = 0U;
        hwt->state = HWT101_STATE_IDLE;
        hwt->rx_index = 0U;
    }

    return 0;
}

float HWT101_GetGyroZ(HWT101_t *hwt)
{
    if ((HWT101_ValidateParams(hwt) != 0) || !hwt->enable || !hwt->data.data_valid)
    {
        return 0.0f;
    }

    return hwt->data.gyro_z;
}

float HWT101_GetYaw(HWT101_t *hwt)
{
    if ((HWT101_ValidateParams(hwt) != 0) || !hwt->enable || !hwt->data.data_valid)
    {
        return 0.0f;
    }

    return hwt->data.yaw;
}

HWT101_Data_t *HWT101_GetData(HWT101_t *hwt)
{
    if ((HWT101_ValidateParams(hwt) != 0) || !hwt->enable || !hwt->data.data_valid)
    {
        return NULL;
    }

    return &hwt->data;
}

int8_t HWT101_SaveConfig(HWT101_t *hwt)
{
    if ((HWT101_ValidateParams(hwt) != 0) || !hwt->enable)
    {
        return -1;
    }

    my_printf(hwt->hw.huart, "\xFF\xAA\x00\x00\x00");
    HAL_Delay(100);
    return 0;
}

int8_t HWT101_SetBaudRate(HWT101_t *hwt, uint8_t baud_code)
{
    if ((HWT101_ValidateParams(hwt) != 0) || !hwt->enable)
    {
        return -1;
    }

    if ((baud_code < 1U) || (baud_code > 7U))
    {
        return -1;
    }

    if (HWT101_UnlockRegister(hwt) != 0)
    {
        return -1;
    }

    if (HWT101_SendCommand(hwt, HWT101_REG_BAUD, (uint16_t)baud_code) != 0)
    {
        return -1;
    }

    if (HWT101_SaveConfig(hwt) != 0)
    {
        return -1;
    }

    HAL_Delay(200);
    return 0;
}

int8_t HWT101_SetOutputRate(HWT101_t *hwt, uint8_t rate_code)
{
    if ((HWT101_ValidateParams(hwt) != 0) || !hwt->enable)
    {
        return -1;
    }

    if ((rate_code < 1U) || (rate_code > 13U) || (rate_code == 10U))
    {
        return -1;
    }

    if (HWT101_UnlockRegister(hwt) != 0)
    {
        return -1;
    }

    if (HWT101_SendCommand(hwt, HWT101_REG_RRATE, (uint16_t)rate_code) != 0)
    {
        return -1;
    }

    if (HWT101_SaveConfig(hwt) != 0)
    {
        return -1;
    }

    HAL_Delay(200);
    return 0;
}

int8_t HWT101_StartManualCalibration(HWT101_t *hwt)
{
    if ((HWT101_ValidateParams(hwt) != 0) || !hwt->enable)
    {
        return -1;
    }

    if (HWT101_UnlockRegister(hwt) != 0)
    {
        return -1;
    }

    if (HWT101_SendCommand(hwt, HWT101_REG_MANUALCALI, 0x0001U) != 0)
    {
        return -1;
    }

    if (HWT101_SaveConfig(hwt) != 0)
    {
        return -1;
    }

    HAL_Delay(500);
    return 0;
}

int8_t HWT101_StopManualCalibration(HWT101_t *hwt)
{
    if ((HWT101_ValidateParams(hwt) != 0) || !hwt->enable)
    {
        return -1;
    }

    if (HWT101_UnlockRegister(hwt) != 0)
    {
        return -1;
    }

    if (HWT101_SendCommand(hwt, HWT101_REG_MANUALCALI, 0x0004U) != 0)
    {
        return -1;
    }

    if (HWT101_SaveConfig(hwt) != 0)
    {
        return -1;
    }

    HAL_Delay(500);
    return 0;
}

int8_t HWT101_ResetYaw(HWT101_t *hwt)
{
    if ((HWT101_ValidateParams(hwt) != 0) || !hwt->enable)
    {
        return -1;
    }

    if (HWT101_UnlockRegister(hwt) != 0)
    {
        return -1;
    }

    if (HWT101_SendCommand(hwt, HWT101_REG_CALIYAW, 0x0000U) != 0)
    {
        return -1;
    }

    if (HWT101_SaveConfig(hwt) != 0)
    {
        return -1;
    }

    HAL_Delay(500);
    return 0;
}

static int8_t HWT101_ValidateParams(HWT101_t *hwt)
{
    if ((hwt == NULL) || (hwt->hw.huart == NULL))
    {
        return -1;
    }

    return 0;
}

static uint8_t HWT101_CalculateChecksum(uint8_t *data, uint8_t length)
{
    uint8_t checksum = 0U;
    uint8_t i;

    for (i = 0U; i < length; i++)
    {
        checksum = (uint8_t)(checksum + data[i]);
    }

    return checksum;
}

static int8_t HWT101_ParseGyroPacket(HWT101_t *hwt, uint8_t *packet)
{
    hwt->data.gyro_z_raw = HWT101_ConvertGyroData(packet[4], packet[5]);
    hwt->data.gyro_z = HWT101_ConvertGyroData(packet[6], packet[7]);
    hwt->data.timestamp = HAL_GetTick();
    hwt->data.data_valid = 1U;
    return 0;
}

static int8_t HWT101_ParseAnglePacket(HWT101_t *hwt, uint8_t *packet)
{
    hwt->data.roll = HWT101_ConvertAngleData(packet[2], packet[3]);
    hwt->data.pitch = HWT101_ConvertAngleData(packet[4], packet[5]);
    hwt->data.yaw = HWT101_ConvertAngleData(packet[6], packet[7]);
    hwt->data.version = (uint16_t)((packet[9] << 8) | packet[8]);
    hwt->data.timestamp = HAL_GetTick();
    hwt->data.data_valid = 1U;
    return 0;
}

static float HWT101_ConvertGyroData(uint8_t low, uint8_t high)
{
    int16_t raw_data = (int16_t)((high << 8) | low);
    return ((float)raw_data / 32768.0f) * 2000.0f;
}

static float HWT101_ConvertAngleData(uint8_t low, uint8_t high)
{
    int16_t raw_data = (int16_t)((high << 8) | low);
    return ((float)raw_data / 32768.0f) * 180.0f;
}

static int8_t HWT101_SendCommand(HWT101_t *hwt, uint8_t reg_addr, uint16_t data)
{
    uint8_t data_low;
    uint8_t data_high;

    if (hwt == NULL)
    {
        return -1;
    }

    data_low = (uint8_t)(data & 0xFFU);
    data_high = (uint8_t)((data >> 8) & 0xFFU);

    my_printf(hwt->hw.huart, "\xFF\xAA%c%c%c", reg_addr, data_low, data_high);
    HAL_Delay(100);
    return 0;
}

static int8_t HWT101_UnlockRegister(HWT101_t *hwt)
{
    if (hwt == NULL)
    {
        return -1;
    }

    my_printf(hwt->hw.huart, "\xFF\xAA\x69\x88\xB5");
    HAL_Delay(100);
    return 0;
}
