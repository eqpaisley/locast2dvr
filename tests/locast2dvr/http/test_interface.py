import json
import subprocess
import types
import unittest
from xml.etree import ElementTree

from flask import Flask
from flask.wrappers import Response
from locast2dvr.http.interface import HTTPInterface, Signal, _log_output, _readline, _stream
from locast2dvr.utils import Configuration
from mock import MagicMock, PropertyMock, patch


class TestHTTPInterface(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Configuration({
            "device_model": "DEVICE_MODEL",
            "device_version": "1.23.4",
            "bind_address": "5.4.3.2",
            "device_firmware": "DEVICE_FIRMWARE",
            "tuner_count": 3,
            "multiplex": False
        })
        port = 6077
        self.locast_service = MagicMock()
        self.locast_service.city = "Chicago"
        self.locast_service.get_stations = MagicMock()
        self.locast_service.get_stations.return_value = [
            {
                "name": "NAME1",
                "callSign": "CBS",
                "city": "Chicago",
                "id": "1234",
                "channel": "1.1",
            },
            {
                "name": "2.1 NAME2",
                "city": "Chicago",
                "id": "4321",
                "channel": "2.1",
            }
        ]
        self.host_and_port = f'{self.config.bind_address}:{port}'
        app = HTTPInterface(self.config, port, "TEST_UID", self.locast_service)
        app.config['DEBUG'] = True
        app.config['TESTING'] = True
        self.client = app.test_client()

    def test_initialization(self):
        app = HTTPInterface(MagicMock(), 6077, "TEST_UID", MagicMock())
        self.assertIsInstance(app, Flask)

    def test_device_xml_valid(self):
        for url in ['/', '/device.xml']:
            xml = self.client.get(url).data.decode('utf-8')
            try:
                ElementTree.fromstring(xml)
            except:
                self.fail(f"Invalid XML: {xml}")

    @patch("locast2dvr.http.interface.render_template")
    def test_device_xml(self, render_template: MagicMock):
        for url in ['/', '/device.xml']:
            render_template.return_value = "Hello"
            self.client.get(url)
            render_template.assert_called_with(
                'device.xml',
                device_model="DEVICE_MODEL",
                device_version="1.23.4",
                friendly_name="Chicago",
                uid='TEST_UID',
                host_and_port='5.4.3.2:6077'
            )

    def test_discover(self):
        json_data = self.client.get('/discover.json').data.decode('utf-8')
        data = json.loads(json_data)

        expected = {
            "FriendlyName": "Chicago",
            "Manufacturer": "locast2dvr",
            "ModelNumber": "DEVICE_MODEL",
            "FirmwareName": "DEVICE_FIRMWARE",
            "TunerCount": 3,
            "FirmwareVersion": "1.23.4",
            "DeviceID": "TEST_UID",
            "DeviceAuth": "locast2dvr",
            "BaseURL": f"http://5.4.3.2:6077",
            "LineupURL": f"http://5.4.3.2:6077/lineup.json"
        }
        self.assertEqual(data, expected)

    def test_m3u_no_multiplex(self):
        for url in ['/lineup.m3u', '/tuner.m3u']:
            data = self.client.get(url).data.decode('utf-8')

            self.locast_service.get_stations.assert_called()
            expected = (
                '#EXTM3U\n'
                '#EXTINF:-1 tvg-id="channel.1234" tvg-name="CBS" tvg-logo="None" tvg-chno="1.1" group-title="Chicago;Network", CBS\n'
                'http://5.4.3.2:6077/watch/1234.m3u\n'
                '\n'
                '#EXTINF:-1 tvg-id="channel.4321" tvg-name="NAME2" tvg-logo="None" tvg-chno="2.1" group-title="Chicago", NAME2\n'
                'http://5.4.3.2:6077/watch/4321.m3u\n\n'
            )

            expected = expected.lstrip()
            self.maxDiff = 1000
            self.assertEqual(data, expected)

    def test_m3u_multiplex(self):
        self.config.multiplex = True
        for url in ['/lineup.m3u', '/tuner.m3u']:

            data = self.client.get(url).data.decode('utf-8')

            self.locast_service.get_stations.assert_called()
            expected = (
                '#EXTM3U\n'
                '#EXTINF:-1 tvg-id="channel.1234" tvg-name="CBS (Chicago)" tvg-logo="None" tvg-chno="1.1" group-title="Chicago;Network", CBS (Chicago)\n'
                'http://5.4.3.2:6077/watch/1234.m3u\n'
                '\n'
                '#EXTINF:-1 tvg-id="channel.4321" tvg-name="NAME2 (Chicago)" tvg-logo="None" tvg-chno="2.1" group-title="Chicago", NAME2 (Chicago)\n'
                'http://5.4.3.2:6077/watch/4321.m3u\n\n'
            )

            expected = expected.lstrip()
            self.maxDiff = 1000
            self.assertEqual(data, expected)

    def test_lineup_json(self):
        data = self.client.get('/lineup.json').data.decode('utf-8')
        expected = [
            {
                "GuideNumber": "1.1",
                "GuideName": "NAME1",
                "URL": "http://5.4.3.2:6077/watch/1234"
            },
            {
                "GuideNumber": "2.1",
                "GuideName": "2.1 NAME2",
                "URL": "http://5.4.3.2:6077/watch/4321"
            }
        ]
        self.assertEqual(json.loads(data), expected)

    def test_lineup_xml_valid(self):
        xml = self.client.get('/lineup.xml').data.decode('utf-8')
        try:
            ElementTree.fromstring(xml)
        except:
            self.fail(f"Invalid XML: {xml}")

    def test_epg(self):
        data = self.client.get('/epg').data.decode('utf-8')
        self.assertEqual(json.loads(data), self.locast_service.get_stations())


def free_var(val):
    def nested():
        return val
    return nested.__closure__[0]


def nested(outer, innerName, **freeVars):
    if isinstance(outer, (types.FunctionType, types.MethodType)):
        outer = outer.__getattribute__('__code__')
    for const in outer.co_consts:
        if isinstance(const, types.CodeType) and const.co_name == innerName:
            return types.FunctionType(const, globals(), None, None, tuple(
                free_var(freeVars[name]) for name in const.co_freevars))


class TestInterfaceWatch(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Configuration({
            "bind_address": "5.4.3.2",
            "ffmpeg": "ffmpeg_bin",
            "bytes_per_read": 1024,
            "verbose": 0
        })
        self.port = 6077
        self.locast_service = MagicMock()
        self.locast_service.city = "Chicago"
        self.app = HTTPInterface(self.config, self.port,
                                 "TEST_UID", self.locast_service)
        self.client = self.app.test_client()

    def test_watch_m3u(self):
        self.locast_service.get_station_stream_uri.return_value = "http://actual_url"
        response: Response = self.client.get('/watch/1234.m3u')
        self.assertIsInstance(response, Response)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "http://actual_url")

    @patch('locast2dvr.http.interface.Signal')
    @patch('locast2dvr.http.interface._log_output')
    @patch('locast2dvr.http.interface._stream')
    @patch('locast2dvr.http.interface.threading.Thread')
    @patch('locast2dvr.http.interface.subprocess.Popen')
    def test_watch(self, Popen: MagicMock, Thread: MagicMock, _stream: MagicMock, _log_output: MagicMock, Signal: MagicMock):
        self.locast_service.get_station_stream_uri.return_value = "http://actual_url"
        Popen.return_value = ffmpeg_proc = MagicMock()
        ffmpeg_proc.stderr = stderr = MagicMock()
        Thread.return_value = thread = MagicMock()
        Signal.return_value = signal = MagicMock()

        ffmpeg_proc.stdout.read.side_effect = ["a", "b", "c"]

        response: Response = self.client.get('/watch/1234')

        Popen.assert_called_once_with([
            'ffmpeg_bin', '-i', 'http://actual_url',
            '-codec', 'copy', '-f', 'mpegts', 'pipe:1',
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertIsInstance(response, Response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type,
                         'video/mpeg; codecs="avc1.4D401E')

        Thread.assert_called_once_with(target=_log_output, args=({
            'bind_address': '5.4.3.2',
            'ffmpeg': 'ffmpeg_bin', 'bytes_per_read': 1024, 'verbose': 0
        }, stderr, signal))
        thread.setDaemon.assert_called_once_with(True)
        thread.start.assert_called()

        _stream.assert_called_once_with(self.config, ffmpeg_proc, signal)


class TestInterfaceEPGXML(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Configuration({
            "device_model": "DEVICE_MODEL",
            "device_version": "1.23.4",
            "bind_address": "5.4.3.2",
            "device_firmware": "DEVICE_FIRMWARE",
            "tuner_count": 3
        })
        port = 6077
        self.locast_service = MagicMock()
        self.locast_service.city = "Chicago"
        self.locast_service.get_stations = MagicMock()
        self.locast_service.get_stations.return_value = [
            {
                "name": "NAME1",
                "callSign": "CALLSIGN1",
                "city": "Chicago",
                "timezone": "America/Chicago",
                "id": "1234",
                "channel": "1.1",
                "listings": [
                    {
                        "startTime": 1610582400000,
                        "duration": 1800,
                        "title": "ProgramTitle",
                        "description": "Program Description",
                        "releaseDate": 1161561600000,
                        "genres": "News",
                        "preferredImage": "http://programimage",
                        "preferredImageHeight": 360,
                        "preferredImageWidth": 240,
                        "videoProperties": "CC, HD 720p, HDTV, Stereo",
                    }
                ]
            },
            {
                "name": "2.1 NAME2",
                "city": "Chicago",
                "timezone": "America/Chicago",
                "id": "4321",
                "channel": "2.1",
                "listings": [
                    {
                        "startTime": 1610582400000,
                        "duration": 1800,
                        "title": "ProgramTitle",
                        "description": "Program Description",
                        "releaseDate": 1161561600000,
                        "genres": "horror, action",
                        "preferredImage": "http://programimage",
                        "preferredImageHeight": 360,
                        "preferredImageWidth": 240,
                        "episodeNumber": 10,
                        "seasonNumber": 2,
                        "videoProperties": "CC, Stereo"
                    }
                ]
            },
            {
                "name": "2.1 NAME2",
                "city": "Chicago",
                "timezone": "America/Chicago",
                "id": "4321",
                "channel": "2.1",
                "listings": [
                    {
                        "startTime": 1610582400000,
                        "duration": 1800,
                        "title": "ProgramTitle",
                        "description": "Program Description",
                        "releaseDate": 1161561600000,
                        "genres": "horror, action",
                        "preferredImage": "http://programimage",
                        "preferredImageHeight": 360,
                        "preferredImageWidth": 240,
                        "videoProperties": "CC, Stereo",
                        "airdate": 1610582400
                    }
                ]
            }
        ]
        self.host_and_port = f'{self.config.bind_address}:{port}'
        app = HTTPInterface(self.config, port, "TEST_UID", self.locast_service)
        app.config['DEBUG'] = True
        app.config['TESTING'] = True
        self.client = app.test_client()

    def test_epg_xml_valid(self):
        xml = self.client.get('/epg.xml').data.decode('utf-8')
        try:
            ElementTree.fromstring(xml)
        except:
            self.fail(f"Invalid XML: {xml}")


class TestInterfaceLineupStatus(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Configuration({
            "bind_address": "5.4.3.2",
        })
        self.port = 6077
        self.locast_service = MagicMock()

    def test_lineup_status(self):
        app = HTTPInterface(self.config, self.port,
                            "TEST_UID", self.locast_service)
        self.client = app.test_client()

        json_data = self.client.get('/lineup_status.json').data.decode('utf-8')
        data = json.loads(json_data)

        expected = {
            "ScanInProgress": False,
            "ScanPossible": True,
            "Source": "Antenna",
            "SourceList": ["Antenna"]
        }
        self.assertEqual(data, expected)

    def test_lineup_status_scanning(self):
        app = HTTPInterface(self.config, self.port,
                            "TEST_UID", self.locast_service, True)
        self.client = app.test_client()

        json_data = self.client.get('/lineup_status.json').data.decode('utf-8')
        data = json.loads(json_data)

        expected = {
            "ScanInProgress": True,
            "Progress": 50,
            "Found": 5
        }
        self.assertEqual(data, expected)

    def test_lineup_post(self):
        app = HTTPInterface(self.config, self.port,
                            "TEST_UID", self.locast_service)
        self.client = app.test_client()

        response = self.client.get('/lineup.post?scan=start')
        self.assertEqual(response.status_code, 204)

        response = self.client.get('/lineup.post?scan=foo')
        self.assertEqual(response.status_code, 400)


class TestConfig(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Configuration({
            "bind_address": "5.4.3.2",
            "password": "foo"
        })
        self.port = 6077
        self.locast_service = MagicMock()

    def test_lineup_status(self):
        app = HTTPInterface(self.config, self.port,
                            "TEST_UID", self.locast_service)
        self.client = app.test_client()
        json_data = self.client.get('/config').data.decode('utf-8')
        data = json.loads(json_data)

        expected = {
            "bind_address": "5.4.3.2",
            "password": "*********"
        }
        self.assertEqual(data, expected)


class TestSignal(unittest.TestCase):
    def test_init(self):
        s1 = Signal(True)
        s2 = Signal(False)
        self.assertEqual(s1.running(), True)
        self.assertEqual(s2.running(), False)
        s1.stop()
        self.assertEqual(s1.running(), False)


class TestLogOutput(unittest.TestCase):
    def test_no_verbose(self):
        config = Configuration({
            'verbose': 0
        })
        stderr = MagicMock()
        signal = MagicMock()
        signal.running = PropertyMock()

        _log_output(config, stderr, signal)

        stderr.readline.assert_not_called()
        signal.running.assert_not_called()

    @patch('locast2dvr.http.interface.logging.getLogger')
    @patch('locast2dvr.http.interface._readline')
    def test_verbose(self, _readline: MagicMock, getLogger: MagicMock):
        config = Configuration({
            'verbose': 1
        })
        stderr = MagicMock()
        signal = MagicMock()
        signal.running = MagicMock()
        signal.running.side_effect = [True, True, False]
        _readline.side_effect = ['foo', '']
        getLogger.return_value = logger = MagicMock()

        _log_output(config, stderr, signal)

        getLogger.assert_called_once_with("ffmpeg")
        logger.info.assert_called_once_with("foo")
        _readline.assert_called_with(stderr)
        signal.running.assert_called()

    def raise_exception():
        raise Exception

    @patch('locast2dvr.http.interface.logging.getLogger')
    @patch('locast2dvr.http.interface._readline')
    def test_verbose_exception(self, _readline: MagicMock, getLogger: MagicMock):
        config = Configuration({
            'verbose': 1
        })
        stderr = MagicMock()
        signal = MagicMock()
        signal.running = MagicMock()
        signal.running.side_effect = [True, False]
        _readline.side_effect = self.raise_exception
        getLogger.return_value = logger = MagicMock()

        _log_output(config, stderr, signal)

        getLogger.assert_called_once_with("ffmpeg")
        logger.info.assert_not_called()
        _readline.assert_called_with(stderr)
        signal.running.assert_called()

    def test_readline(self):
        stderr = MagicMock()
        stderr.readline.return_value = b'\xf0\x9f\x98\x8a foo bar '
        res = _readline(stderr)
        self.assertEqual(res, "😊 foo bar")


class TestStream(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Configuration({
            'bytes_per_read': 1024
        })

    def test_stream(self):
        ffmpeg_proc = MagicMock()
        ffmpeg_proc.stdout.read = read_mock = MagicMock()
        signal = Signal(True)
        read_mock.side_effect = ['foo', 'bar', 'baz']

        s = _stream(self.config, ffmpeg_proc, signal)

        ret = next(s)
        read_mock.assert_called_with(1024)
        self.assertEqual(ret, 'foo')
        ret = next(s)
        self.assertEqual(ret, 'bar')
        ret = next(s)
        self.assertEqual(ret, 'baz')
        self.assertTrue(signal.running())
        ffmpeg_proc.terminate.assert_not_called()
        ffmpeg_proc.communicate.assert_not_called()

    def raise_exception():
        raise Exception

    def test_stream_exception(self):
        ffmpeg_proc = MagicMock()
        ffmpeg_proc.stdout.read = read_mock = MagicMock()
        signal = Signal(True)
        read_mock.side_effect = self.raise_exception

        s = _stream(self.config, ffmpeg_proc, signal)

        try:
            next(s)
        except StopIteration:
            pass

        read_mock.assert_called_with(1024)

        ffmpeg_proc.terminate.assert_called()
        ffmpeg_proc.communicate.assert_called()
