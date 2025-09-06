from config import Config
import requests

node_name = "example_node"

path = Config.NODE_SPEC_URL.format(node_name = node_name)
url = f"{Config.SERVER_URI}{path}"

session = requests.Session()
response = session.post(url, json = {"status": "ONLINE"})
# response = self.api_client.put(url, data=self.config.to_dict())