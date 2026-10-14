/* Bounded binary HTTP upload for the RA80 RAM-only boot path. */
#ifndef RA80_RAM_UPLOAD_H
#define RA80_RAM_UPLOAD_H

#define RA80_RAM_HEADER_MAX 2048
enum { RA80_UPLOAD_MORE, RA80_UPLOAD_DONE };
enum { RA80_UPLOAD_BAD_REQUEST = -1, RA80_UPLOAD_SIZE = -2,
	RA80_UPLOAD_LENGTH = -3, RA80_UPLOAD_OVERFLOW = -4 };

struct ra80_ram_upload {
	char header[RA80_RAM_HEADER_MAX];
	unsigned int header_len;
	unsigned long length, received;
	int header_done, error;
};

static int ra80_header_name(const char *key, unsigned long len, const char *want)
{
	unsigned long i;
	if (strlen(want) != len)
		return 0;
	for (i = 0; i < len; i++) {
		char c = key[i];
		if (c >= 'A' && c <= 'Z')
			c += 'a' - 'A';
		if (c != want[i])
			return 0;
	}
	return 1;
}

static int ra80_ram_upload_headers(struct ra80_ram_upload *s, unsigned long limit)
{
	char *line, *end, *colon, *value, *last;
	int have_length = 0, binary_type = 0;
	end = strstr(s->header, "\r\n");
	if (!end || (unsigned long)(end - s->header) != 22 ||
	    (strncmp(s->header, "POST /ramboot HTTP/1.0", 22) &&
	     strncmp(s->header, "POST /ramboot HTTP/1.1", 22)))
		return RA80_UPLOAD_BAD_REQUEST;
	for (line = end + 2; line[0] != '\r'; line = end + 2) {
		end = strstr(line, "\r\n");
		if (!end)
			return RA80_UPLOAD_BAD_REQUEST;
		colon = memchr(line, ':', end - line);
		if (!colon)
			return RA80_UPLOAD_BAD_REQUEST;
		value = colon + 1;
		while (value < end && (*value == ' ' || *value == '\t'))
			value++;
		last = end;
		while (last > value && (last[-1] == ' ' || last[-1] == '\t'))
			last--;
		if (ra80_header_name(line, colon - line, "transfer-encoding"))
			return RA80_UPLOAD_BAD_REQUEST;
		if (ra80_header_name(line, colon - line, "content-type")) {
			if (binary_type++ || last - value != 24 ||
			    strncmp(value, "application/octet-stream", 24))
				return RA80_UPLOAD_BAD_REQUEST;
		}
		if (!ra80_header_name(line, colon - line, "content-length"))
			continue;
		if (have_length++ || value == last)
			return RA80_UPLOAD_LENGTH;
		for (; value < last; value++) {
			unsigned int digit = *value - '0';
			if (digit > 9)
				return RA80_UPLOAD_LENGTH;
			if (digit > limit || s->length > (limit - digit) / 10)
				return RA80_UPLOAD_SIZE;
			s->length = s->length * 10 + digit;
		}
	}
	if (!have_length)
		return RA80_UPLOAD_LENGTH;
	if (!binary_type)
		return RA80_UPLOAD_BAD_REQUEST;
	if (s->length < 40 || s->length > limit)
		return RA80_UPLOAD_SIZE;
	s->header_done = 1;
	return 0;
}

/* Return only the body slice belonging to this call; never copy HTTP bytes. */
static int ra80_ram_upload_feed(struct ra80_ram_upload *s, const char *data,
	unsigned long len, unsigned long limit, unsigned long *offset,
	unsigned long *count)
{
	unsigned long pos = 0;
	int ret;
	*offset = *count = 0;
	if (s->error)
		return s->error;
	while (!s->header_done && pos < len) {
		if (s->header_len >= sizeof(s->header) - 1 || !data[pos]) {
			s->error = RA80_UPLOAD_BAD_REQUEST;
			return s->error;
		}
		s->header[s->header_len++] = data[pos++];
		s->header[s->header_len] = 0;
		if (s->header_len < 4 ||
		    memcmp(s->header + s->header_len - 4, "\r\n\r\n", 4))
			continue;
		ret = ra80_ram_upload_headers(s, limit);
		if (ret) {
			s->error = ret;
			return ret;
		}
	}
	if (!s->header_done)
		return RA80_UPLOAD_MORE;
	if (len - pos > s->length - s->received) {
		s->error = RA80_UPLOAD_OVERFLOW;
		return s->error;
	}
	*offset = pos;
	*count = len - pos;
	s->received += *count;
	return s->received == s->length ? RA80_UPLOAD_DONE : RA80_UPLOAD_MORE;
}
#endif
