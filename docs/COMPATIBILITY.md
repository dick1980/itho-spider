# Configuration and identity

The integration uses domain and component folder `itho_spider`, configuration schema version 2, and one configuration per Spider. Keep stored identifiers and options stable when changing code.

- Configuration unique ID: Spider radio address.
- Device identifier: `(itho_spider, radio_address)` for gateway and Spider devices.
- Entity unique ID: `<spider_address>_<entity_key>`.
- Multiple entries share one transport for the same USB gateway.
- Battery waiting is an option per Spider, independent of other Spiders.

Protocol changes must retain source validation, echo rejection, confirmed commands, bounded retries and the shared radio rate limit. Physical gateway removal is a user action and cannot be inferred from a timer or missing traffic.
