import logging
import os
import threading
from unittest import TestCase

from textwrap import dedent

from mailinglogger.SummarisingLogger import SummarisingLogger
from mailinglogger.common import exit_handler_manager
from mailinglogger.tests.shared import DummySMTP, removeHandlers, _check_sent_message


class TestSummarisingLogger(TestCase):

    def setUp(self):
        removeHandlers()
        DummySMTP.install()

    def tearDown(self):
        DummySMTP.remove()
        exit_handler_manager.clear_at_exit_handlers()

    def test_imports(self):
        pass

    def create(self, *args, **kw):
        kw['atexit'] = False
        self.handler = SummarisingLogger(*args, **kw)
        self.logger = logging.getLogger('')
        self.logger.addHandler(self.handler)

    def test_do_send_empty(self):
        self.create('from@example.com', ('to@example.com',))
        logging.shutdown()
        self.assertEqual(len(DummySMTP.sent), 1)

    def test_dont_send_empty(self):
        self.create('from@example.com', ('to@example.com',),
                    send_empty_entries=False)
        logging.shutdown()
        self.assertEqual(len(DummySMTP.sent), 0)

    def test_send_level_filters(self):
        self.create('from@example.com', ('to@example.com',),
                    send_level=logging.CRITICAL)
        self.logger.warning('This line will not be sent')
        logging.shutdown()
        self.assertEqual(len(DummySMTP.sent), 0)

    def test_send_level_includes_lower_level(self):
        self.create('from@example.com', ('to@example.com',),
                    send_level=logging.CRITICAL)
        self.logger.warning('a warning')
        self.logger.critical('something critical')
        logging.shutdown()
        self.assertEqual(len(DummySMTP.sent), 1)
        message_text = DummySMTP.sent[0].msg
        _check_sent_message('a warning', message_text)
        _check_sent_message('something critical', message_text)

    def test_tmpfile_goes_away(self):
        self.create('from@example.com', ('to@example.com',))
        os.remove(self.handler.filename)
        logging.shutdown()
        self.assertEqual(len(DummySMTP.sent), 1)

    def test_default_charset(self):
        self.create('from@example.com', ('to@example.com',), )
        self.logger.critical(u"accentu\u00E9")
        logging.shutdown()
        m = DummySMTP.sent[0].msg
        # lovely, utf-8 encoded goodness
        self.assertTrue('Subject: Summary of Log Messages (CRITICAL)' in m, m)
        self.assertTrue('Content-Type: text/plain; charset="utf-8"' in m, m)
        self.assertTrue('\nYWNjZW50dcOp' in m, m)

    def test_specified_charset(self):
        self.create('from@example.com', ('to@example.com',),
                    charset='iso-8859-1')
        self.logger.critical(u"accentu\u00E9")
        logging.shutdown()
        m = DummySMTP.sent[0].msg
        # lovely, latin-1 encoded goodness
        self.assertTrue('\naccentu=E9' in m, m)
        self.assertTrue(
            'Content-Type: text/plain; charset="iso-8859-1"' in m, m)
        self.assertTrue('Subject: Summary of Log Messages (CRITICAL)' in m, m)

    def test_template(self):
        self.create('from@example.com', ('to@example.com',),
                    template='<before>%s<after>')
        logging.critical('message')
        logging.shutdown()
        m = DummySMTP.sent[0].msg
        self.assertTrue('Subject: Summary of Log Messages (CRITICAL)' in m, m)
        _check_sent_message('<before>message\n<after>', m)

    def test_specified_content_type(self):
        self.create('from@example.com', ('to@example.com',),
                    content_type='foo/bar')
        self.logger.critical(u"message")
        logging.shutdown()
        m = DummySMTP.sent[0].msg
        # NB: we drop the 'foo'
        self.assertTrue('Content-Type: text/bar' in m, m)

    def test_flood_level_exceeded(self):
        self.create('from@example.com', ('to@example.com', ),
                    flood_level=3)
        self.handler.setFormatter(
            logging.Formatter('%(levelname)s - %(message)s')
        )
        for i in range(10):
            logging.warning('message %s', i)
        logging.shutdown()
        self.assertEqual(len(DummySMTP.sent), 1)
        m = DummySMTP.sent[0].msg
        self.assertTrue('Subject: Summary of Log Messages (WARNING)' in m, m)
        _check_sent_message('\n'.join([
            'WARNING - message 0',
            'WARNING - message 1',
            'WARNING - message 2',
            'CRITICAL - 2 messages not included as flood limit of 3 exceeded',
            'WARNING - message 5',
            'WARNING - message 6',
            'WARNING - message 7',
            'WARNING - message 8',
        ]), m)

    def test_interesting_stuff_after_flood_level_provide_context(self):
        self.create('from@example.com', ('to@example.com',),
                    flood_level=6, provide_context=logging.WARNING)
        self.handler.setFormatter(
            logging.Formatter('%(levelname)s - %(message)s')
        )
        for i in range(5):
            logging.info('Something interesting happens before %s', i)
            logging.warning('message %s', i)
        logging.shutdown()
        self.assertEqual(len(DummySMTP.sent), 1)
        m = DummySMTP.sent[0].msg
        self.assertTrue('Subject: Summary of Log Messages (WARNING)' in m, m)
        _check_sent_message('\n'.join([
            'INFO - Something interesting happens before 0',
            'WARNING - message 0',
            'INFO - Something interesting happens before 1',
            'WARNING - message 1',
            'INFO - Something interesting happens before 2',
            'WARNING - message 2',
            'INFO - Something interesting happens before 3',
            'WARNING - message 3',
            'INFO - Something interesting happens before 4',
            'WARNING - message 4',
        ]), m)

    def test_too_much_interesting_stuff_after_flood_still_truncated(self):
        self.create('from@example.com', ('to@example.com',),
                    flood_level=6, provide_context=logging.WARNING)
        self.handler.setFormatter(
            logging.Formatter('%(levelname)s - %(message)s')
        )
        for i in range(20):
            logging.info('Something interesting happens before %s', i)
            logging.warning('message %s', i)
        logging.shutdown()
        self.assertEqual(len(DummySMTP.sent), 1)
        m = DummySMTP.sent[0].msg
        self.assertTrue('Subject: Summary of Log Messages (WARNING)' in m, m)
        _check_sent_message(dedent("""\
            INFO - Something interesting happens before 0
            WARNING - message 0
            INFO - Something interesting happens before 1
            WARNING - message 1
            INFO - Something interesting happens before 2
            WARNING - message 2
            CRITICAL - 21 messages not included as flood limit of 6 exceeded
            WARNING - message 13
            INFO - Something interesting happens before 14
            WARNING - message 14
            INFO - Something interesting happens before 15
            WARNING - message 15
            INFO - Something interesting happens before 16
            WARNING - message 16
            INFO - Something interesting happens before 17
            WARNING - message 17
            INFO - Something interesting happens before 18
            WARNING - message 18
            INFO - Something interesting happens before 19
            WARNING - message 19
        """), m)

    def test_flood_highest_level_still_recorded(self):
        self.create('from@example.com', ('to@example.com', ),
                    flood_level=1)
        self.handler.setFormatter(
            logging.Formatter('%(levelname)s - %(message)s')
        )
        logging.info('included')
        logging.warning('filtered')
        for i in range(5):
            logging.info('after %i', i)
        logging.shutdown()
        self.assertEqual(len(DummySMTP.sent), 1)
        m = DummySMTP.sent[0].msg
        self.assertTrue('Subject: Summary of Log Messages (WARNING)' in m, m)
        _check_sent_message('\n'.join([
            'INFO - included',
            'CRITICAL - 1 messages not included as flood limit of 1 exceeded',
            'INFO - after 0',
        ]), m)

    def test_flood_except_for_tail(self):
        self.create('from@example.com', ('to@example.com', ),
                    flood_level=1)
        self.handler.setFormatter(
            logging.Formatter('%(levelname)s - %(message)s')
        )
        logging.warning('message 1')
        logging.warning('message 2')
        logging.shutdown()
        self.assertEqual(len(DummySMTP.sent), 1)
        m = DummySMTP.sent[0].msg
        self.assertTrue('Subject: Summary of Log Messages (WARNING)' in m, m)
        _check_sent_message('\n'.join([
            'WARNING - message 1',
            'WARNING - message 2',
        ]), m)

    def test_reopen(self):
        self.create('from@example.com', ('to@example.com',))
        self.handler.reopen()
        logging.shutdown()
        self.assertEqual(len(DummySMTP.sent), 2)

    def test_safe_close(self):
        self.create('from@example.com', ('to@example.com', ))
        threads = []
        for i in range(2):
            t = threading.Thread(target=self.handler.close)
            threads.append(t)
            t.start()
        [t.join() for t in threads]
        self.assertEqual(len(DummySMTP.sent), 1)
