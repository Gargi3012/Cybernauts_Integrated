import requests

url = "http://localhost:8000/inbound-call"
data = {
    "To": "+917082968702",
    "From": "+18303546921"
}
# Test Plivo answer XML webhook endpoint
response = requests.post(url, data=data)
print("Status:", response.status_code)
print("XML:\n", response.text)
