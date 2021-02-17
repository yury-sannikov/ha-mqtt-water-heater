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
    WaterHeaterEntity,
    PLATFORM_SCHEMA
)
from homeassistant.const import (
    CONF_ICON,
    CONF_NAME,
    ATTR_TEMPERATURE,
    TEMP_CELSIUS,
    CONF_FORCE_UPDATE,
    CONF_VALUE_TEMPLATE,
    CONF_UNIQUE_ID
)
from homeassistant.util.temperature import convert as convert_temperature

from homeassistant.components.mqtt.const import (
    CONF_QOS,
    CONF_STATE_TOPIC,
)

from homeassistant.components.mqtt.mixins import (
    MqttAvailability,
    MQTT_AVAILABILITY_SCHEMA
)

from homeassistant.components.mqtt import (
    MQTT_RO_PLATFORM_SCHEMA,
    DATA_MQTT,
    subscription
)

from .const import (
    DOMAIN,
    CONF_WATER_HEATER_TARGET_TEMPERATURE,
    CONF_WATER_HEATER_MIN_TEMPERATURE,
    CONF_WATER_HEATER_MAX_TEMPERATURE,
    CONF_WATER_HEATER_SET_TEMPERATURE_TOPIC
)

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
            vol.Required(CONF_WATER_HEATER_SET_TEMPERATURE_TOPIC): cv.string,
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


class MQTTWaterHeater(WaterHeaterEntity, MqttAvailability):
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
        command_topic = config.get(CONF_WATER_HEATER_SET_TEMPERATURE_TOPIC)


        # Set instance variables
        self._target_temperature = target_temperature
        self._unit_of_measurement = TEMP_CELSIUS
        self._away = away
        self._current_operation = current_operation
        self._min_temp = min_temp
        self._max_temp = max_temp
        self._command_topic = command_topic

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
        # Notify boiler
        self.hass.components.mqtt.publish(self._command_topic, str(self._target_temperature))
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

            if template is not None:
                # Skip if we're not able to parse template. Will try to parse as float
                try:
                    payload = template.async_render_with_possible_json_value(
                        payload, self._target_temperature
                    )
                except Exception as ex:
                    _LOGGER.debug("unable to parse json payload. Payload: %s, error: %s", str(payload), ex)

            try:
                # payload expected to be a float
                temperature = float(payload)
                # zero temperature might indicate no data
                if temperature <= 0.0:
                    _LOGGER.debug("received temperature %s is less/eq than zero. Skipping", str(payload))
                    return
                self._target_temperature = temperature
            except Exception as ex:
                _LOGGER.debug("unable to set _target_temperature. Payload: %s, error: %s", str(payload), ex)
                return

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
