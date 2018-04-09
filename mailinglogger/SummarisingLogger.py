import os
from collections import deque
from logging import CRITICAL, FileHandler, Formatter, LogRecord
from tempfile import mkstemp

from copy import copy
from six import PY2

from mailinglogger.MailingLogger import MailingLogger
from mailinglogger.common import exit_handler_manager

flood_template = '%i messages not included as flood limit of %i exceeded'


class SummarisingLogger(FileHandler):

    maxlevelno = 0
    message_count = 0
    tail = None

    def __init__(self,
                 fromaddr,
                 toaddrs,
                 mailhost='localhost',
                 subject='Summary of Log Messages (%(levelname)s)',
                 send_empty_entries=True,
                 atexit=True,
                 username=None,
                 password=None,
                 headers=None,
                 send_level=None,
                 template=None,
                 charset='utf-8',
                 content_type='text/plain',
                 flood_level=100,
                 provide_context=None,
                 ):
        # create the "real" mailinglogger
        self.mailer = MailingLogger(fromaddr,
                                    toaddrs,
                                    mailhost,
                                    subject,
                                    send_empty_entries,
                                    username=username,
                                    password=password,
                                    headers=headers,
                                    template=template,
                                    charset=charset,
                                    content_type=content_type)
        # set the mailing logger's log format
        self.mailer.setFormatter(Formatter('%(message)s'))
        self.send_level = send_level
        self.charset = charset
        self.flood_level = flood_level
        self.open()
        # register our close method
        if atexit:
            exit_handler_manager.register_at_exit_handler(self.close)

        self._tail = deque(maxlen=5)

        self.provide_context = provide_context
        self._additional_message_and_context = deque(maxlen=5)


    def open(self):
        # create a temp file logger to store log entries
        self.fd, self.filename = mkstemp()
        FileHandler.__init__(self, self.filename, 'w', encoding=self.charset)
        self.closed = False

    def setLevel(self, lvl):
        self.mailer.setLevel(lvl)
        FileHandler.setLevel(self, lvl)

    def emit(self, record):
        if self.closed:
            return

        if record.levelno > self.maxlevelno:
            self.maxlevelno = record.levelno

        self.message_count += 1
        self._tail.append(record)
        if self.message_count == self.flood_level:
            self._records_emitted_prior_to_flood_limit = copy(self._tail)

        if self.message_count > self.flood_level:
            if self.provide_context and record.levelno >= self.provide_context:
                self._additional_message_and_context.append(copy(self._tail))
        else:
            FileHandler.emit(self, record)

    def close(self):
        if self.closed:
            return
        self.closed = True

        if self.message_count > self.flood_level:
            records_to_emit = []
            for message_with_context in self._additional_message_and_context:
                for record in message_with_context:
                    if record not in records_to_emit:
                        records_to_emit.append(record)

            for record in self._tail:
                if record not in records_to_emit:
                    records_to_emit.append(record)

            records_to_emit = [r for r in records_to_emit if r not in self._records_emitted_prior_to_flood_limit]

            hidden = self.message_count - self.flood_level - len(records_to_emit)
            if hidden > 0:
                # send critical error
                FileHandler.emit(self, LogRecord(
                    name='flood',
                    level=CRITICAL,
                    pathname='',
                    lineno=0,
                    msg=flood_template % (hidden, self.flood_level),
                    args=(),
                    exc_info=None
                ))
            for record in records_to_emit:
                FileHandler.emit(self, record)


        FileHandler.close(self)


        if PY2:
            f = os.fdopen(self.fd)
            summary = f.read().decode(self.charset)
        else:
            f = open(self.fd, encoding=self.charset)
            summary = f.read()
        f.close()
        try:
            summary.encode('ascii')
            self.mailer.charset = 'ascii'
            if PY2:
                summary = summary.encode('ascii')
        except UnicodeEncodeError:
            pass


        if os.path.exists(self.filename):
            os.remove(self.filename)
        if self.send_level is None or self.maxlevelno >= self.send_level:
            self.mailer.handle(
                LogRecord(
                    name='Summary',
                    level=self.maxlevelno,
                    pathname='',
                    lineno=0,
                    msg=summary,
                    args=(),
                    exc_info=None
                )
            )

    def reopen(self):
        self.close()
        self.open()
