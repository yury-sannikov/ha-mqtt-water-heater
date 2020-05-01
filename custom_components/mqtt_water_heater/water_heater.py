"""Demo platform that offers a fake water heater device."""
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.core import callback
import logging
import json

from homeassistant.components.water_heater import (
    SUPPORT_AWAY_MODE,
    SUPPORT_OPERATION_MODE,
    SUPPORT_TARGET_TEMPERATURE,
    WaterHeaterDevice,
    PLATFORM_SCHEMA
)
from homeassistant.const import (
    CONF_ICON,
    CONF_NAME,
    ATTR_TEMPERATURE,
    TEMP_CELSIUS,
    CONF_FORCE_UPDATE,
    CONF_VALUE_TEMPLATE
)
from homeassistant.util.temperature import convert as convert_temperature
from homeassistant.components.mqtt import (
    # CONF_COMMAND_TOPIC,
    CONF_QOS,
    # CONF_RETAIN,
    CONF_STATE_TOPIC,
    CONF_UNIQUE_ID,
    # MqttAttributes,
    MqttAvailability,
    MQTT_RO_PLATFORM_SCHEMA,
    MQTT_AVAILABILITY_SCHEMA,
    # MqttDiscoveryUpdate,
    # MqttEntityDeviceInfo,
    subscription
)

from .const import DOMAIN, CONF_WATER_HEATER_TARGET_TEMPERATURE, CONF_WATER_HEATER_MIN_TEMPERATURE, CONF_WATER_HEATER_MAX_TEMPERATURE

DEPENDENCIES = ["mqtt"]

SUPPORT_FLAGS_HEATER = (
    SUPPORT_TARGET_TEMPERATURE | SUPPORT_OPERATION_MODE | SUPPORT_AWAY_MODE
)

DEFAULT_NAME = "Water Heater"
DEFAULT_FORCE_UPDATE = False
PLATFORM_SCHEMA = (
    MQTT_RO_PLATFORM_SCHEMA.extend(
        {
            vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
            vol.Optional(CONF_FORCE_UPDATE, default=DEFAULT_FORCE_UPDATE): cv.boolean,
            vol.Optional(CONF_ICON): cv.icon,
            vol.Optional(CONF_WATER_HEATER_TARGET_TEMPERATURE, default=38): cv.positive_int,
            vol.Optional(CONF_WATER_HEATER_MIN_TEMPERATURE, default=35): cv.positive_int,
            vol.Optional(CONF_WATER_HEATER_MAX_TEMPERATURE, default=60): cv.positive_int,
        }
    )
    .extend(MQTT_AVAILABILITY_SCHEMA.schema)
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    async_add_entities(
        [
            #MQTTWaterHeater(name, 38, TEMP_CELSIUS, False, "eco"),
            MQTTWaterHeater(config, async_add_entities, discovery_info),
        ]
    )


async def async_setup_entry(hass, config_entry, async_add_entities):
    await async_setup_platform(hass, {}, async_add_entities)


class MQTTWaterHeater(WaterHeaterDevice, MqttAvailability):
    def __init__(
        self, config, config_entry, discovery_data
    ):
        self._config = config
        self._unique_id = config.get(CONF_UNIQUE_ID)
        self._sub_state = None
        self._expiration_trigger = None


        MqttAvailability.__init__(self, config)

        ####  WaterHeaterDevice init
        self._operation_list = [
            "eco",
            "electric",
            "performance",
            "high_demand",
            "heat_pump",
            "gas",
            "off",
        ]
        # Get configs (or defaults)
        target_temperature = config.get(CONF_WATER_HEATER_TARGET_TEMPERATURE, 38)
        away = None
        current_operation = "gas"
        min_temp = config.get(CONF_WATER_HEATER_MIN_TEMPERATURE, 35)
        max_temp = config.get(CONF_WATER_HEATER_MAX_TEMPERATURE, 60)


        # Set instance variables
        self._target_temperature = target_temperature
        self._unit_of_measurement = TEMP_CELSIUS
        self._away = away
        self._current_operation = current_operation
        self._min_temp = min_temp
        self._max_temp = max_temp

        # build Support Flags
        self._support_flags = SUPPORT_FLAGS_HEATER
        if target_temperature is not None:
            self._support_flags = self._support_flags | SUPPORT_TARGET_TEMPERATURE
        if away is not None:
            self._support_flags = self._support_flags | SUPPORT_AWAY_MODE
        if current_operation is not None:
            self._support_flags = self._support_flags | SUPPORT_OPERATION_MODE



    @property
    def unique_id(self):
        """Return a unique ID."""
        return self._unique_id

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._support_flags

    @property
    def should_poll(self):
        """Return the polling state."""
        return False

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._config[CONF_NAME]

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return self._unit_of_measurement

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temperature

    @property
    def current_operation(self):
        """Return current operation ie. heat, cool, idle."""
        return self._current_operation

    @property
    def operation_list(self):
        """Return the list of available operation modes."""
        return self._operation_list

    @property
    def is_away_mode_on(self):
        """Return if away mode is on."""
        return self._away

    ## TODO: send MQTT message to set boiler temperature
    def set_temperature(self, **kwargs):
        """Set new target temperatures."""
        self._target_temperature = kwargs.get(ATTR_TEMPERATURE)
        _LOGGER.error("WH set_temperature received: %s", str(self._target_temperature))
        self.schedule_update_ha_state()

    def set_operation_mode(self, operation_mode):
        """Set new operation mode."""
        self._current_operation = operation_mode
        self.schedule_update_ha_state()

    def turn_away_mode_on(self):
        """Turn away mode on."""
        self._away = True
        self.schedule_update_ha_state()

    def turn_away_mode_off(self):
        """Turn away mode off."""
        self._away = False
        self.schedule_update_ha_state()

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        return convert_temperature(
            self._min_temp, TEMP_CELSIUS, self.temperature_unit
        )

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        return convert_temperature(
            self._max_temp, TEMP_CELSIUS, self.temperature_unit
        )

    @property
    def state(self):
        """Return the state of the entity."""
        return self._target_temperature

    @property
    def force_update(self):
        """Force update."""
        return self._config[CONF_FORCE_UPDATE]

    ###
    # Handle MQTT stuff
    ###
    async def async_added_to_hass(self):
        """Subscribe to MQTT events."""
        await super().async_added_to_hass()
        await self._subscribe_topics()

    async def discovery_update(self, discovery_payload):
        """Handle updated discovery message."""
        config = PLATFORM_SCHEMA(discovery_payload)
        self._config = config
        await self._subscribe_topics()
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self):
        """Unsubscribe when removed."""
        self._sub_state = await subscription.async_unsubscribe_topics(
            self.hass, self._sub_state
        )
        await MqttAvailability.async_will_remove_from_hass(self)

    async def _subscribe_topics(self):
        """(Re)Subscribe to topics."""

        template = self._config.get(CONF_VALUE_TEMPLATE)
        if template is not None:
            template.hass = self.hass

        @callback
        ##@log_messages(self.hass, self.entity_id)
        def message_received(msg):
            """Handle new MQTT messages."""
            payload = msg.payload

            # if template is not None:
            #     payload = template.async_render_with_possible_json_value(
            #         payload, self._state
            #     )
            # self._state = payload

            try:
                self._target_temperature = float(payload)
            except Exception as ex:
                _LOGGER.debug("unable to set _target_temperature. Payload: %s, error: %s", string(payload), ex)

            self.async_write_ha_state()

        self._sub_state = await subscription.async_subscribe_topics(
            self.hass,
            self._sub_state,
            {
                "state_topic": {
                    "topic": self._config[CONF_STATE_TOPIC],
                    "msg_callback": message_received,
                    "qos": self._config[CONF_QOS],
                }
            },
        )

##################################################################################################







# """Support for Rheem EcoNet water heaters."""
# import datetime
# import logging

# import voluptuous as vol

# from homeassistant.components.water_heater import (
#     PLATFORM_SCHEMA,
#     STATE_ECO,
#     STATE_ELECTRIC,
#     STATE_GAS,
#     STATE_HEAT_PUMP,
#     STATE_HIGH_DEMAND,
#     STATE_OFF,
#     STATE_PERFORMANCE,
#     SUPPORT_OPERATION_MODE,
#     SUPPORT_TARGET_TEMPERATURE,
#     WaterHeaterDevice,
# )
# from homeassistant.const import (
#     ATTR_ENTITY_ID,
#     ATTR_TEMPERATURE,
#     CONF_PASSWORD,
#     CONF_USERNAME,
#     TEMP_CELSIUS,
# )
# import homeassistant.helpers.config_validation as cv

# from .const import DOMAIN, SERVICE_ADD_VACATION, SERVICE_DELETE_VACATION

# _LOGGER = logging.getLogger(__name__)

# ATTR_VACATION_START = "next_vacation_start_date"
# ATTR_VACATION_END = "next_vacation_end_date"
# ATTR_ON_VACATION = "on_vacation"
# ATTR_TODAYS_ENERGY_USAGE = "todays_energy_usage"
# ATTR_IN_USE = "in_use"

# ATTR_START_DATE = "start_date"
# ATTR_END_DATE = "end_date"

# ATTR_LOWER_TEMP = "lower_temp"
# ATTR_UPPER_TEMP = "upper_temp"
# ATTR_IS_ENABLED = "is_enabled"

# SUPPORT_FLAGS_HEATER = SUPPORT_TARGET_TEMPERATURE | SUPPORT_OPERATION_MODE

# ADD_VACATION_SCHEMA = vol.Schema(
#     {
#         vol.Optional(ATTR_ENTITY_ID): cv.entity_ids,
#         vol.Optional(ATTR_START_DATE): cv.positive_int,
#         vol.Required(ATTR_END_DATE): cv.positive_int,
#     }
# )

# DELETE_VACATION_SCHEMA = vol.Schema({vol.Optional(ATTR_ENTITY_ID): cv.entity_ids})

# ECONET_DATA = "mqtt_water_heater"

# ECONET_STATE_TO_HA = {
#     "Energy Saver": STATE_ECO,
#     "gas": STATE_GAS,
#     "High Demand": STATE_HIGH_DEMAND,
#     "Off": STATE_OFF,
#     "Performance": STATE_PERFORMANCE,
#     "Heat Pump Only": STATE_HEAT_PUMP,
#     "Electric-Only": STATE_ELECTRIC,
#     "Electric": STATE_ELECTRIC,
#     "Heat Pump": STATE_HEAT_PUMP,
# }

# PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
#     {vol.Required(CONF_USERNAME): cv.string, vol.Required(CONF_PASSWORD): cv.string}
# )


# def setup_platform(hass, config, add_entities, discovery_info=None):
#     """Set up the EcoNet water heaters."""

#     hass.data[ECONET_DATA] = {}
#     hass.data[ECONET_DATA]["water_heaters"] = []

#     username = config.get(CONF_USERNAME)
#     password = config.get(CONF_PASSWORD)

#     hass_water_heaters = [
#         EcoNetWaterHeater('demo22')
#     ]
#     add_entities(hass_water_heaters)
#     hass.data[ECONET_DATA]["water_heaters"].extend(hass_water_heaters)

#     def service_handle(service):
#         """Handle the service calls."""
#         entity_ids = service.data.get("entity_id")
#         all_heaters = hass.data[ECONET_DATA]["water_heaters"]
#         _heaters = [
#             x for x in all_heaters if not entity_ids or x.entity_id in entity_ids
#         ]

#         for _water_heater in _heaters:
#             if service.service == SERVICE_ADD_VACATION:
#                 start = service.data.get(ATTR_START_DATE)
#                 end = service.data.get(ATTR_END_DATE)
#                 _water_heater.add_vacation(start, end)
#             if service.service == SERVICE_DELETE_VACATION:
#                 for vacation in _water_heater.water_heater.vacations:
#                     vacation.delete()

#             _water_heater.schedule_update_ha_state(True)

#     hass.services.register(
#         DOMAIN, SERVICE_ADD_VACATION, service_handle, schema=ADD_VACATION_SCHEMA
#     )

#     hass.services.register(
#         DOMAIN, SERVICE_DELETE_VACATION, service_handle, schema=DELETE_VACATION_SCHEMA
#     )


# class EcoNetWaterHeater(WaterHeaterDevice):
#     """Representation of an EcoNet water heater."""

#     def __init__(self, water_heater):
#         """Initialize the water heater."""
#         self.water_heater = {
#           "name": water_heater,
#           "is_connected": True,
#           "set_point": 38,
#           "min_set_point": 35,
#           "max_set_point": 60
#         }
#         # self.supported_modes = self.water_heater.supported_modes
#         # self.econet_state_to_ha = {}
#         # self.ha_state_to_econet = {}
#         # for mode in ECONET_STATE_TO_HA:
#         #     if mode in self.supported_modes:
#         #         self.econet_state_to_ha[mode] = ECONET_STATE_TO_HA.get(mode)
#         # for key, value in self.econet_state_to_ha.items():
#         #     self.ha_state_to_econet[value] = key
#         # for mode in self.supported_modes:
#         #     if mode not in ECONET_STATE_TO_HA:
#         #         error = f"Invalid operation mode mapping. {mode} doesn't map. Please report this."
#         #         _LOGGER.error(error)

#     @property
#     def name(self):
#         """Return the device name."""
#         return self.water_heater.name

#     @property
#     def available(self):
#         """Return if the the device is online or not."""
#         return self.water_heater.is_connected

#     @property
#     def temperature_unit(self):
#         """Return the unit of measurement."""
#         return TEMP_CELSIUS

#     @property
#     def device_state_attributes(self):
#         """Return the optional device state attributes."""
#         data = {}
#         data[ATTR_LOWER_TEMP] = 35
#         data[ATTR_UPPER_TEMP] = 60
#         data[ATTR_IS_ENABLED] = ATTR_TEMPERATURE
#         # vacations = self.water_heater.get_vacations()
#         # if vacations:
#         #     data[ATTR_VACATION_START] = vacations[0].start_date
#         #     data[ATTR_VACATION_END] = vacations[0].end_date
#         # data[ATTR_ON_VACATION] = self.water_heater.is_on_vacation
#         # todays_usage = self.water_heater.total_usage_for_today
#         # if todays_usage:
#         #     data[ATTR_TODAYS_ENERGY_USAGE] = todays_usage
#         # data[ATTR_IN_USE] = self.water_heater.in_use

#         # if self.water_heater.lower_temp is not None:
#         #     data[ATTR_LOWER_TEMP] = round(self.water_heater.lower_temp, 2)
#         # if self.water_heater.upper_temp is not None:
#         #     data[ATTR_UPPER_TEMP] = round(self.water_heater.upper_temp, 2)
#         # if self.water_heater.is_enabled is not None:
#         #     data[ATTR_IS_ENABLED] = self.water_heater.is_enabled

#         return data

#     @property
#     def current_operation(self):
#         """
#         Return current operation as one of the following.

#         ["eco", "heat_pump", "high_demand", "electric_only"]
#         """
#         current_op = "eco" # self.econet_state_to_ha.get(self.water_heater.mode)
#         return current_op

#     @property
#     def operation_list(self):
#         """List of available operation modes."""
#         op_list = ["eco"]
#         # for mode in self.supported_modes:
#         #     ha_mode = self.econet_state_to_ha.get(mode)
#         #     if ha_mode is not None:
#         #         op_list.append(ha_mode)
#         return op_list

#     @property
#     def supported_features(self):
#         """Return the list of supported features."""
#         return SUPPORT_FLAGS_HEATER

#     def set_temperature(self, **kwargs):
#         """Set new target temperature."""
#         target_temp = kwargs.get(ATTR_TEMPERATURE)
#         if target_temp is not None:
#             self.water_heater.set_point = target_temp
#             _LOGGER.error("set_temperature called" + str(target_temp))
#         else:
#             _LOGGER.error("A target temperature must be provided")

#     def set_operation_mode(self, operation_mode):
#         """Set operation mode."""
#         pass
#         # op_mode_to_set = self.ha_state_to_econet.get(operation_mode)
#         # if op_mode_to_set is not None:
#         #     self.water_heater.set_mode(op_mode_to_set)
#         # else:
#         #     _LOGGER.error("An operation mode must be provided")

#     def add_vacation(self, start, end):
#         """Add a vacation to this water heater."""
#         pass
#         # if not start:
#         #     start = datetime.datetime.now()
#         # else:
#         #     start = datetime.datetime.fromtimestamp(start)
#         # end = datetime.datetime.fromtimestamp(end)
#         # self.water_heater.set_vacation_mode(start, end)

#     def update(self):
#         """Get the latest date."""
#         pass
#         # self.water_heater.update_state()

#     @property
#     def target_temperature(self):
#         """Return the temperature we try to reach."""
#         return self.water_heater.set_point

#     @property
#     def min_temp(self):
#         """Return the minimum temperature."""
#         return self.water_heater.min_set_point

#     @property
#     def max_temp(self):
#         """Return the maximum temperature."""
#         return self.water_heater.max_set_point