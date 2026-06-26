import urllib.request, json, urllib.error
req = urllib.request.Request('http://localhost:8000/lesson-intelligence/macro-plan', data=json.dumps({'sub_institute_id': 1, 'standard_id': 43, 'subject_id': 3975, 'syear': 2024}).encode(), headers={'Content-Type': 'application/json'}, method='POST')
try:
    urllib.request.urlopen(req)
except urllib.error.HTTPError as e:
    print(e.read().decode())
