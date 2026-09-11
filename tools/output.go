package tools

import "sync"

// cappedBuffer collects at most limit bytes of command output.
//
// Truncation happens while reading, not after: buffering the whole stream and
// trimming afterwards means a command that emits gigabytes is still read into
// memory in full before the limit is applied.
type cappedBuffer struct {
	mu        sync.Mutex
	buf       []byte
	limit     int
	truncated bool
}

func (c *cappedBuffer) Write(p []byte) (int, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if room := c.limit - len(c.buf); room > 0 {
		if len(p) <= room {
			c.buf = append(c.buf, p...)
			return len(p), nil
		}
		c.buf = append(c.buf, p[:room]...)
	}
	c.truncated = true
	// Report a full write so the child keeps running. Returning a short count
	// would look like a write error and could surface as a broken pipe.
	return len(p), nil
}

func (c *cappedBuffer) String() string {
	c.mu.Lock()
	defer c.mu.Unlock()
	out := string(c.buf)
	if c.truncated {
		out += "\n... truncated"
	}
	return out
}
