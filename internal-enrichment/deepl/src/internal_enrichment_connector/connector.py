from pycti import OpenCTIConnectorHelper

from .client_api import ConnectorClient
from .config_loader import ConfigConnector
from .converter_to_stix import ConverterToStix
import requests
import deepl
import os


class ConnectorDeepl:
    """
    Specifications of the internal enrichment connector

    This class encapsulates the main actions, expected to be run by any internal enrichment connector.
    Note that the attributes defined below will be complemented per each connector type.
    This type of connector aim to enrich a data (Observables) created or modified in the OpenCTI core platform.
    It will create a STIX bundle and send it in a RabbitMQ queue.
    The STIX bundle in the queue will be processed by the workers.
    This type of connector uses the basic methods of the helper.
    Ingesting a bundle allow the connector to be compatible with the playbook automation feature.


    ---

    Attributes
        - `config (ConfigConnector())`:
            Initialize the connector with necessary configuration environment variables

        - `helper (OpenCTIConnectorHelper(config))`:
            This is the helper to use.
            ALL connectors have to instantiate the connector helper with configurations.
            Doing this will do a lot of operations behind the scene.

        - `converter_to_stix (ConnectorConverter(helper))`:
            Provide methods for converting various types of input data into STIX 2.1 objects.

    ---

    Best practices
        - `self.helper.connector_logger.[info/debug/warning/error]` is used when logging a message
        - `self.helper.stix2_create_bundle(stix_objects)` is used when creating a bundle
        - `self.helper.send_stix2_bundle(stix_objects_bundle)` is used to send the bundle to RabbitMQ

    """

    def __init__(self, config: ConfigConnector, helper: OpenCTIConnectorHelper):
        """
        Initialize the Connector with necessary configurations
        """

        # Load configuration file and connection helper
        self.config = config
        self.helper = helper
        self.client = ConnectorClient(self.helper, self.config)
        self.converter_to_stix = ConverterToStix(self.helper)
        self.deepl_client = deepl.DeepLClient(self.config.api_key)

        # Define variables
        self.author = None
        self.tlp = None
        self.stix_objects_list = []

    def get_files_from_report(self, report_id):
        report = self.helper.api.report.read(id=report_id, withFiles=True)
        for i in report["importFiles"]:
            # When a file was already translated we do not want to do it again
            if i["name"].startswith("translated_"):
                self.helper.connector_logger.info(
                    "Filename "
                    + i["name"]
                    + " indicates that it has already been translated, therefor skipping it"
                )
                continue
            headers = {"Authorization": "Bearer " + self.config.opencti_token}
            url = self.config.opencti_url + "/storage/get/" + str(i["id"])
            r = requests.get(url, headers=headers, stream=True, verify=False)
            if r.status_code == 200:
                output_filepath = os.getcwd() + "/reports/" + i["name"]
                translated_filepath = (
                    os.getcwd()
                    + "/reports/translated_"
                    + self.config.target_language
                    + "_"
                    + i["name"]
                )
                try:
                    with open(output_filepath, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024):
                            f.write(chunk)
                    self.helper.connector_logger.info(
                        "Downloaded report "
                        + i["name"]
                        + " with size "
                        + str(os.path.getsize(output_filepath))
                    )

                    # Checking against Deepl API limits
                    # https://developers.deepl.com/docs/resources/usage-limits
                    not_supported = False
                    if os.path.getsize(output_filepath) >= 10485760 and i[
                        "name"
                    ].endswith(".docx"):
                        not_supported = True
                    elif os.path.getsize(output_filepath) >= 10485760 and i[
                        "name"
                    ].endswith(".pptx"):
                        not_supported = True
                    elif os.path.getsize(output_filepath) >= 10485760 and i[
                        "name"
                    ].endswith(".xlsx"):
                        not_supported = True
                    elif os.path.getsize(output_filepath) >= 10485760 and i[
                        "name"
                    ].endswith(".pdf"):
                        not_supported = True
                    elif os.path.getsize(output_filepath) >= 1048576 and i[
                        "name"
                    ].endswith(".txt"):
                        not_supported = True
                    elif os.path.getsize(output_filepath) >= 5242880 and i[
                        "name"
                    ].endswith(".html"):
                        not_supported = True
                    elif os.path.getsize(output_filepath) >= 10485760 and i[
                        "name"
                    ].endswith(".xlf"):
                        not_supported = True
                    elif os.path.getsize(output_filepath) >= 10485760 and i[
                        "name"
                    ].endswith(".xliff"):
                        not_supported = True
                    elif os.path.getsize(output_filepath) >= 153600 and i[
                        "name"
                    ].endswith(".srt"):
                        not_supported = True

                    if not not_supported:
                        self.deepl_client.translate_document_from_filepath(
                            output_filepath,
                            translated_filepath,
                            target_lang=self.config.target_language,
                        )
                        self.helper.api.stix_domain_object.add_file(
                            id=report_id, file_name=translated_filepath
                        )
                    else:
                        self.helper.connector_logger.info(
                            "Downloaded report "
                            + i["name"]
                            + " with size "
                            + str(os.path.getsize(output_filepath))
                            + " is larger than Deepl API limits allow, skipping"
                        )
                except Exception as ex:
                    self.helper.connector_logger.error(
                        "Error while translating report: " + str(ex)
                    )
                finally:
                    self.helper.connector_logger.error("Cleaning up temporary reports")
                    if os.path.exists(output_filepath):
                        os.remove(output_filepath)
                    if os.path.exists(translated_filepath):
                        os.remove(translated_filepath)
        return

    def entity_in_scope(self, data) -> bool:
        """
        Security to limit playbook triggers to something other than the initial scope
        :param data: Dictionary of data
        :return: boolean
        """
        scopes = self.helper.connect_scope.lower().replace(" ", "").split(",")
        entity_split = data["entity_id"].split("--")
        entity_type = entity_split[0].lower()

        if entity_type in scopes:
            return True
        else:
            return False

    def extract_and_check_markings(self, opencti_entity: dict) -> None:
        """
        Extract TLP, and we check if the variable "max_tlp" is less than
        or equal to the markings access of the entity from OpenCTI
        If this is true, we can send the data to connector for enrichment.
        :param opencti_entity: Dict of observable from OpenCTI
        :return: Boolean
        """
        if len(opencti_entity["objectMarking"]) != 0:
            for marking_definition in opencti_entity["objectMarking"]:
                if marking_definition["definition_type"] == "TLP":
                    self.tlp = marking_definition["definition"]

        valid_max_tlp = self.helper.check_max_tlp(self.tlp, self.config.max_tlp)

        if not valid_max_tlp:
            raise ValueError(
                "[CONNECTOR] Do not send any data, TLP of the observable is greater than MAX TLP,"
                "the connector does not has access to this observable, please check the group of the connector user"
            )

    def process_message(self, data: dict) -> str:
        """
        Get the observable created/modified in OpenCTI and check which type to send for process
        The data passed in the data parameter is a dictionary with the following structure as shown in
        https://docs.opencti.io/latest/development/connectors/#additional-implementations
        :param data: dict of data to process
        :return: string
        """
        try:
            self.helper.connector_logger.info(str(self.config))
            opencti_entity = data["enrichment_entity"]
            self.extract_and_check_markings(opencti_entity)

            # To enrich the data, you can add more STIX object in stix_objects
            self.stix_objects_list = data["stix_objects"]
            report = data["stix_entity"]

            self.get_files_from_report(report["id"])
            if self.entity_in_scope(data):
                self.get_files_from_report(report["id"])
            else:
                if not data.get("event_type"):
                    # If it is not in scope AND entity bundle passed through playbook, we should return the original bundle unchanged
                    self._send_bundle(self.stix_objects_list)
                else:
                    # self.helper.connector_logger.info(
                    #     "[CONNECTOR] Skip the following entity as it does not concern "
                    #     "the initial scope found in the config connector: ",
                    #     {"entity_id": opencti_entity["entity_id"]},
                    # )
                    raise ValueError(
                        f"Failed to process report, {opencti_entity['entity_type']} is not a supported entity type."
                    )
        except Exception as err:
            # Handling other unexpected exceptions
            return self.helper.connector_logger.error(
                "[CONNECTOR] Unexpected Error occurred", {"error_message": str(err)}
            )

    def _send_bundle(self, stix_objects: list) -> str:
        stix_objects_bundle = self.helper.stix2_create_bundle(stix_objects)
        bundles_sent = self.helper.send_stix2_bundle(stix_objects_bundle)

        info_msg = (
            "Sending " + str(len(bundles_sent)) + " stix bundle(s) for worker import"
        )
        return info_msg

    def run(self) -> None:
        """
        Run the main process in self.helper.listen() method
        The method continuously monitors a message queue associated with a specific connector
        The connector have to listen a specific queue to get and then enrich the information.
        The helper provide an easy way to listen to the events.
        """
        self.helper.listen(message_callback=self.process_message)
