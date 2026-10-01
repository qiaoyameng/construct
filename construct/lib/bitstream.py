from io import BlockingIOError
from time import sleep
from sys import maxsize


class RestreamedBytesIO(object):

    def __init__(self, substream, decoder, decoderunit, encoder, encoderunit):
        self.substream = substream
        self.encoder = encoder
        self.encoderunit = encoderunit
        self.decoder = decoder
        self.decoderunit = decoderunit
        self.rbuffer = b""
        self.wbuffer = b""
        self.sincereadwritten = 0

    def read(self, count=None):
        if count is None:
            while True:
                data = self.substream.read(self.decoderunit)
                if data is None or len(data) == 0:
                    break
                self.rbuffer += self.decoder(data)
            data, self.rbuffer = self.rbuffer, b''
            self.sincereadwritten += len(data)
            return data

        else:
            if count < 0:
                raise ValueError("count cannot be negative")
            while len(self.rbuffer) < count:
                data = self.substream.read(self.decoderunit)
                if data is None or len(data) == 0:
                    return b''
                self.rbuffer += self.decoder(data)
            data, self.rbuffer = self.rbuffer[:count], self.rbuffer[count:]
            self.sincereadwritten += count
            return data

    def write(self, data):
        self.wbuffer += data
        datalen = len(data)
        while len(self.wbuffer) >= self.encoderunit:
            data, self.wbuffer = self.wbuffer[:self.encoderunit], self.wbuffer[self.encoderunit:]
            self.substream.write(self.encoder(data))
        self.sincereadwritten += datalen
        return datalen

    def close(self):
        if len(self.rbuffer):
            raise ValueError("closing stream but %d unread bytes remain, %d is decoded unit" % (len(self.rbuffer), self.decoderunit))
        if len(self.wbuffer):
            raise ValueError("closing stream but %d unwritten bytes remain, %d is encoded unit" % (len(self.wbuffer), self.encoderunit))

    def seek(self, at, whence=0):
        if whence == 0 and at == self.sincereadwritten:
            pass
        else:
            raise IOError

    def seekable(self):
        return False

    def tell(self):
        """WARNING: tell is correct only on read-only and write-only instances."""
        return self.sincereadwritten

    def tellable(self):
        return True


class SeekableRestreamedBytesIO(object):
    """A restreamed view (like RestreamedBytesIO) that additionally supports
    tell and seek, in logical (decoded) units, for fixed-ratio codecs on top
    of seekable substreams.

    Positions are expressed in decoded bytes (eg. bits for a bytes-to-bits
    decoder). Seeking to a position that falls inside a decoded unit re-reads
    that unit from the substream and keeps the remainder buffered, so reading
    after a cross-byte seek yields the correct bits. On close, the substream
    is rewound by the amount of complete units that were read ahead but left
    unconsumed, so the outer stream position reflects the logical position.

    Only fixed-ratio codecs are supported: the decoder must map every chunk
    of `decoderunit` bytes into the same non-zero amount of bytes (and the
    encoder likewise). Variable-length (de)compression codecs are not
    supported and raise ValueError at construction.

    Write-mode seeking flushes complete encoded units and requires the target
    to be aligned to the encoding unit; unaligned write positions are
    rejected with IOError instead of being silently padded.
    """

    def __init__(self, substream, decoder, decoderunit, encoder, encoderunit):
        if decoderunit <= 0 or encoderunit <= 0:
            raise ValueError("decoder and encoder units must be positive")
        decoded = decoder(bytes(decoderunit))
        if not decoded or len(decoded) != len(decoder(b"\x01" * decoderunit)):
            raise ValueError("decoder is not fixed-ratio, seekable restreaming is not supported")
        encoded = encoder(bytes(encoderunit))
        if not encoded or len(encoded) != len(encoder(b"\x01" * encoderunit)):
            raise ValueError("encoder is not fixed-ratio, seekable restreaming is not supported")
        self.substream = substream
        self.decoder = decoder
        self.decoderunit = decoderunit
        self.encoder = encoder
        self.encoderunit = encoderunit
        self.decodedunit = len(decoded)
        self.encodedunit = len(encoded)
        self.start = substream.tell()
        self.rbuffer = b""
        self.wbuffer = b""
        self.sincereadwritten = 0
        self.mode = None

    def read(self, count=None):
        if self.mode is None:
            self.mode = "r"
        if count is None:
            while True:
                data = self.substream.read(self.decoderunit)
                if data is None or len(data) == 0:
                    break
                self.rbuffer += self.decoder(data)
            data, self.rbuffer = self.rbuffer, b""
            self.sincereadwritten += len(data)
            return data

        else:
            if count < 0:
                raise ValueError("count cannot be negative")
            while len(self.rbuffer) < count:
                data = self.substream.read(self.decoderunit)
                if data is None or len(data) == 0:
                    break
                self.rbuffer += self.decoder(data)
            data, self.rbuffer = self.rbuffer[:count], self.rbuffer[count:]
            self.sincereadwritten += len(data)
            return data

    def write(self, data):
        if self.mode is None:
            self.mode = "w"
        self.wbuffer += data
        datalen = len(data)
        while len(self.wbuffer) >= self.encoderunit:
            data, self.wbuffer = self.wbuffer[:self.encoderunit], self.wbuffer[self.encoderunit:]
            self.substream.write(self.encoder(data))
        self.sincereadwritten += datalen
        return datalen

    def close(self):
        if len(self.rbuffer):
            full, partial = divmod(len(self.rbuffer), self.decodedunit)
            if partial:
                raise ValueError("closing stream but %d unread bytes remain, %d is decoded unit" % (len(self.rbuffer), self.decodedunit))
            self.substream.seek(self.substream.tell() - full * self.decoderunit, 0)
            self.rbuffer = b""
        if len(self.wbuffer):
            raise ValueError("closing stream but %d unwritten bytes remain, %d is encoded unit" % (len(self.wbuffer), self.encoderunit))

    def seek(self, at, whence=0):
        if whence == 1:
            at = self.sincereadwritten + at
        elif whence == 2:
            end = self.substream.seek(0, 2)
            at = (end - self.start) * self.decodedunit // self.decoderunit + at
        if at < 0:
            raise ValueError("cannot seek to negative position %d" % (at,))
        if self.mode == "w":
            while len(self.wbuffer) >= self.encoderunit:
                data, self.wbuffer = self.wbuffer[:self.encoderunit], self.wbuffer[self.encoderunit:]
                self.substream.write(self.encoder(data))
            if len(self.wbuffer):
                raise IOError("cannot seek with %d unwritten bytes pending, %d is encoded unit" % (len(self.wbuffer), self.encoderunit))
            unit, skip = divmod(at, self.encoderunit)
            if skip:
                raise IOError("cannot seek to unaligned position %d in write mode, %d is encoded unit" % (at, self.encoderunit))
            self.substream.seek(self.start + unit * self.encodedunit, 0)
            self.rbuffer = b""
        else:
            unit, skip = divmod(at, self.decodedunit)
            self.substream.seek(self.start + unit * self.decoderunit, 0)
            self.rbuffer = b""
            if skip:
                data = self.substream.read(self.decoderunit)
                if data:
                    self.rbuffer = self.decoder(data)[skip:]
        self.sincereadwritten = at
        return at

    def seekable(self):
        return True

    def tell(self):
        """Returns the logical (decoded) position. WARNING: tell is correct only on read-only and write-only instances."""
        return self.sincereadwritten

    def tellable(self):
        return True


class RebufferedBytesIO(object):

    def __init__(self, substream, tailcutoff=None):
        self.substream = substream
        self.offset = 0
        self.rwbuffer = b""
        self.moved = 0
        self.tailcutoff = tailcutoff

    def read(self, count=None):
        if count is None:
            raise ValueError("count must be integer, reading until EOF not supported")
        startsat = self.offset
        endsat = startsat + count
        if startsat < self.moved:
            raise IOError("could not read because tail was cut off")
        while self.moved + len(self.rwbuffer) < endsat:
            try:
                newdata = self.substream.read(128*1024)
            except BlockingIOError:
                newdata = None
            if not newdata:
                sleep(0)
                continue
            self.rwbuffer += newdata
        data = self.rwbuffer[startsat-self.moved:endsat-self.moved]
        self.offset += count
        if self.tailcutoff is not None and self.moved < self.offset - self.tailcutoff:
            removed = self.offset - self.tailcutoff - self.moved
            self.moved += removed
            self.rwbuffer = self.rwbuffer[removed:]
        if len(data) < count:
            raise IOError("could not read enough bytes, something went wrong")
        return data

    def write(self, data):
        startsat = self.offset
        endsat = startsat + len(data)
        while self.moved + len(self.rwbuffer) < startsat:
            newdata = self.substream.read(128*1024)
            self.rwbuffer += newdata
            if not newdata:
                sleep(0)
        self.rwbuffer = self.rwbuffer[:startsat-self.moved] + data + self.rwbuffer[endsat-self.moved:]
        self.offset = endsat
        if self.tailcutoff is not None and self.moved < self.offset - self.tailcutoff:
            removed = self.offset - self.tailcutoff - self.moved
            self.moved += removed
            self.rwbuffer = self.rwbuffer[removed:]
        return len(data)

    def seek(self, at, whence=0):
        if whence == 0:
            self.offset = at
            return self.offset
        elif whence == 1:
            self.offset += at
            return self.offset
        else:
            raise ValueError("this class seeks only with whence: 0 and 1 (excluded 2)")

    def seekable(self):
        return True

    def tell(self):
        return self.offset

    def tellable(self):
        return True

    def cachedfrom(self):
        return self.moved

    def cachedto(self):
        return self.moved + len(self.rwbuffer)
