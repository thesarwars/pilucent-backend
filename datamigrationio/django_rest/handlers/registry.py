class MigrationHandlerRegistry:
    _registry: dict = {}

    @classmethod
    def register(cls, handler_class):
        """Register a handler class. Can be used as a decorator or called directly."""
        if not handler_class.data_type:
            raise ValueError(f"Handler {handler_class.__name__} must define data_type.")
        cls._registry[handler_class.data_type] = handler_class
        return handler_class

    @classmethod
    def get(cls, data_type: str):
        """Return the handler class for the given data_type, or None."""
        return cls._registry.get(data_type)

    @classmethod
    def all(cls) -> list:
        """Return all registered handler classes."""
        return list(cls._registry.values())

    @classmethod
    def get_all_metadata(cls) -> list:
        """Return metadata dicts for all registered handlers."""
        return [h.get_metadata() for h in cls._registry.values()]

    @classmethod
    def get_valid_data_types(cls) -> list:
        """Return list of all registered data_type strings."""
        return list(cls._registry.keys())
