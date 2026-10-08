from alerting import AlertManager

a = AlertManager()
known = [{'id': 6, 'latitude': 13.126084983333332, 'longitude': 77.80843, 'count': 60}]
a.check(13.126070, 77.80843, 0, 15, known)