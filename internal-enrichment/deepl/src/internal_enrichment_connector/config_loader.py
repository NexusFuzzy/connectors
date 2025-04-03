import os
from pathlib import Path

import yaml
from pycti import get_config_variable


class ConfigConnector:
    def __init__(self):
        """
        Initialize the connector with necessary configurations
        """

        # Load configuration file
        self.load = self._load_config()
        self._initialize_configurations()

    @staticmethod
    def _load_config() -> dict:
        """
        Load the configuration from the YAML file
        :return: Configuration dictionary
        """
        config_file_path = Path(__file__).parents[1].joinpath("config.yml")
        config = (
            yaml.load(open(config_file_path), Loader=yaml.FullLoader)
            if os.path.isfile(config_file_path)
            else {}
        )

        return config

    def _initialize_configurations(self) -> None:
        """
        Connector configuration variables
        :return: None
        """
        # OpenCTI configurations

        # Connector extra parameters
        self.api_key = get_config_variable(
            "CONNECTOR_DEEPL_API_KEY",
            ["connector_deepl", "api_key"],
            self.load,
        )

        self.max_tlp = get_config_variable(
            "CONNECTOR_DEEPL_MAX_TLP",
            ["connector_deepl", "max_tlp"],
            self.load,
        )

        self.target_language = get_config_variable(
            "CONNECTOR_DEEPL_TARGET_LANGUAGE",
            ["connector_deepl", "target_language"],
            self.load,
        )

        self.opencti_url = get_config_variable(
            "OPENCTI_URL",
            ["opencti", "url"],
            self.load,
        )

        self.opencti_token = get_config_variable(
            "OPENCTI_TOKEN",
            ["opencti", "token"],
            self.load,
        )
