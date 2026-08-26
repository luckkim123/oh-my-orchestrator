package wrapper

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"regexp"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/goccy/go-json"
)

func stripTimestampPrefix(line string) string {
	line = strings.TrimSpace(line)
	if strings.HasPrefix(line, "{") {
		var evt struct {
			Message string `json:"message"`
		}
		if err := json.Unmarshal([]byte(line), &evt); err == nil && evt.Message != "" {
			return evt.Message
		}
	}
	if !strings.HasPrefix(line, "[") {
		return line
	}
	if idx := strings.Index(line, "] "); idx >= 0 {
		return line[idx+2:]
	}
	return line
}

// TestConcurrentStressLogger -- high-concurrency stress test
func TestConcurrentStressLogger(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping stress test in short mode")
	}

	logger, err := NewLoggerWithSuffix("stress")
	if err != nil {
		t.Fatal(err)
	}
	defer logger.Close()

	t.Logf("Log file: %s", logger.Path())

	const (
		numGoroutines  = 100  // concurrent goroutines
		logsPerRoutine = 1000 // log lines written per goroutine
		totalExpected  = numGoroutines * logsPerRoutine
	)

	var wg sync.WaitGroup
	start := time.Now()

	// start the concurrent writers
	for i := 0; i < numGoroutines; i++ {
		wg.Add(1)
		go func(id int) {
			defer wg.Done()
			for j := 0; j < logsPerRoutine; j++ {
				logger.Info(fmt.Sprintf("goroutine-%d-msg-%d", id, j))
			}
		}(i)
	}

	wg.Wait()
	logger.Flush()
	elapsed := time.Since(start)

	// read the log file back to verify
	data, err := os.ReadFile(logger.Path())
	if err != nil {
		t.Fatalf("failed to read log file: %v", err)
	}

	lines := strings.Split(strings.TrimSpace(string(data)), "\n")
	actualCount := len(lines)

	t.Logf("Concurrent stress test results:")
	t.Logf("  Goroutines: %d", numGoroutines)
	t.Logf("  Logs per goroutine: %d", logsPerRoutine)
	t.Logf("  Total expected: %d", totalExpected)
	t.Logf("  Total actual: %d", actualCount)
	t.Logf("  Duration: %v", elapsed)
	t.Logf("  Throughput: %.2f logs/sec", float64(totalExpected)/elapsed.Seconds())

	// verify the line count
	if actualCount < totalExpected/10 {
		t.Errorf("too many logs lost: got %d, want at least %d (10%% of %d)",
			actualCount, totalExpected/10, totalExpected)
	}
	t.Logf("Successfully wrote %d/%d logs (%.1f%%)",
		actualCount, totalExpected, float64(actualCount)/float64(totalExpected)*100)

	// verify the format: plain text, no prefix
	formatRE := regexp.MustCompile(`^goroutine-\d+-msg-\d+$`)
	for i, line := range lines[:min(10, len(lines))] {
		msg := stripTimestampPrefix(line)
		if !formatRE.MatchString(msg) {
			t.Errorf("line %d has invalid format: %s", i, line)
		}
	}
}

// TestConcurrentBurstLogger -- bursty traffic test
func TestConcurrentBurstLogger(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping burst test in short mode")
	}

	logger, err := NewLoggerWithSuffix("burst")
	if err != nil {
		t.Fatal(err)
	}
	defer logger.Close()

	t.Logf("Log file: %s", logger.Path())

	const (
		numBursts          = 10
		goroutinesPerBurst = 50
		logsPerGoroutine   = 100
	)

	totalLogs := 0
	start := time.Now()

	// simulate a traffic burst
	for burst := 0; burst < numBursts; burst++ {
		var wg sync.WaitGroup
		for i := 0; i < goroutinesPerBurst; i++ {
			wg.Add(1)
			totalLogs += logsPerGoroutine
			go func(b, g int) {
				defer wg.Done()
				for j := 0; j < logsPerGoroutine; j++ {
					logger.Info(fmt.Sprintf("burst-%d-goroutine-%d-msg-%d", b, g, j))
				}
			}(burst, i)
		}
		wg.Wait()
		time.Sleep(10 * time.Millisecond) // gap between bursts
	}

	logger.Flush()
	elapsed := time.Since(start)

	// verify
	data, err := os.ReadFile(logger.Path())
	if err != nil {
		t.Fatalf("failed to read log file: %v", err)
	}

	lines := strings.Split(strings.TrimSpace(string(data)), "\n")
	actualCount := len(lines)

	t.Logf("Burst test results:")
	t.Logf("  Total bursts: %d", numBursts)
	t.Logf("  Goroutines per burst: %d", goroutinesPerBurst)
	t.Logf("  Expected logs: %d", totalLogs)
	t.Logf("  Actual logs: %d", actualCount)
	t.Logf("  Duration: %v", elapsed)
	t.Logf("  Throughput: %.2f logs/sec", float64(totalLogs)/elapsed.Seconds())

	if actualCount < totalLogs/10 {
		t.Errorf("too many logs lost: got %d, want at least %d (10%% of %d)", actualCount, totalLogs/10, totalLogs)
	}
	t.Logf("Successfully wrote %d/%d logs (%.1f%%)",
		actualCount, totalLogs, float64(actualCount)/float64(totalLogs)*100)
}

// TestLoggerChannelCapacity -- push the channel to its capacity limit
func TestLoggerChannelCapacity(t *testing.T) {
	logger, err := NewLoggerWithSuffix("capacity")
	if err != nil {
		t.Fatal(err)
	}
	defer logger.Close()

	const rapidLogs = 2000 // above the channel capacity (1000)

	start := time.Now()
	for i := 0; i < rapidLogs; i++ {
		logger.Info(fmt.Sprintf("rapid-log-%d", i))
	}
	sendDuration := time.Since(start)

	logger.Flush()
	flushDuration := time.Since(start) - sendDuration

	t.Logf("Channel capacity test:")
	t.Logf("  Logs sent: %d", rapidLogs)
	t.Logf("  Send duration: %v", sendDuration)
	t.Logf("  Flush duration: %v", flushDuration)

	// a reasonable share must still land; non-blocking mode permits some loss
	data, err := os.ReadFile(logger.Path())
	if err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSpace(string(data)), "\n")
	actualCount := len(lines)

	if actualCount < rapidLogs/10 {
		t.Errorf("too many logs lost: got %d, want at least %d (10%% of %d)", actualCount, rapidLogs/10, rapidLogs)
	}
	t.Logf("Logs persisted: %d/%d (%.1f%%)", actualCount, rapidLogs, float64(actualCount)/float64(rapidLogs)*100)
}

// TestLoggerMemoryUsage -- memory usage under load
func TestLoggerMemoryUsage(t *testing.T) {
	logger, err := NewLoggerWithSuffix("memory")
	if err != nil {
		t.Fatal(err)
	}
	defer logger.Close()

	const numLogs = 20000
	longMessage := strings.Repeat("x", 500) // 500-byte message

	start := time.Now()
	for i := 0; i < numLogs; i++ {
		logger.Info(fmt.Sprintf("log-%d-%s", i, longMessage))
	}
	logger.Flush()
	elapsed := time.Since(start)

	// check the file size
	info, err := os.Stat(logger.Path())
	if err != nil {
		t.Fatal(err)
	}

	expectedTotalSize := int64(numLogs * 500) // theoretical minimum total bytes
	expectedMinSize := expectedTotalSize / 10 // tolerate up to 90% loss
	actualSize := info.Size()

	t.Logf("Memory/disk usage test:")
	t.Logf("  Logs written: %d", numLogs)
	t.Logf("  Message size: 500 bytes")
	t.Logf("  File size: %.2f MB", float64(actualSize)/1024/1024)
	t.Logf("  Duration: %v", elapsed)
	t.Logf("  Write speed: %.2f MB/s", float64(actualSize)/1024/1024/elapsed.Seconds())
	t.Logf("  Persistence ratio: %.1f%%", float64(actualSize)/float64(expectedTotalSize)*100)

	if actualSize < expectedMinSize {
		t.Errorf("file size too small: got %d bytes, expected at least %d", actualSize, expectedMinSize)
	}
}

// TestLoggerFlushTimeout -- the Flush timeout mechanism
func TestLoggerFlushTimeout(t *testing.T) {
	logger, err := NewLoggerWithSuffix("flush")
	if err != nil {
		t.Fatal(err)
	}
	defer logger.Close()

	// write some lines
	for i := 0; i < 100; i++ {
		logger.Info(fmt.Sprintf("test-log-%d", i))
	}

	// Flush must finish within a reasonable time
	start := time.Now()
	logger.Flush()
	duration := time.Since(start)

	t.Logf("Flush duration: %v", duration)

	if duration > 6*time.Second {
		t.Errorf("Flush took too long: %v (expected < 6s)", duration)
	}
}

// TestLoggerOrderPreservation -- per-goroutine ordering is preserved
func TestLoggerOrderPreservation(t *testing.T) {
	logger, err := NewLoggerWithSuffix("order")
	if err != nil {
		t.Fatal(err)
	}
	defer logger.Close()

	const numGoroutines = 10
	const logsPerRoutine = 100

	var wg sync.WaitGroup
	for i := 0; i < numGoroutines; i++ {
		wg.Add(1)
		go func(id int) {
			defer wg.Done()
			for j := 0; j < logsPerRoutine; j++ {
				logger.Info(fmt.Sprintf("G%d-SEQ%04d", id, j))
			}
		}(i)
	}

	wg.Wait()
	logger.Flush()

	// read back and check each goroutine's ordering
	data, err := os.ReadFile(logger.Path())
	if err != nil {
		t.Fatal(err)
	}

	scanner := bufio.NewScanner(strings.NewReader(string(data)))
	sequences := make(map[int][]int) // goroutine ID -> sequence numbers

	for scanner.Scan() {
		line := stripTimestampPrefix(scanner.Text())
		var gid, seq int
		// Parse format: G0-SEQ0001 (without INFO: prefix)
		_, err := fmt.Sscanf(line, "G%d-SEQ%04d", &gid, &seq)
		if err != nil {
			t.Errorf("invalid log format: %s (error: %v)", line, err)
			continue
		}
		sequences[gid] = append(sequences[gid], seq)
	}

	// verify ordering within each goroutine
	for gid, seqs := range sequences {
		for i := 0; i < len(seqs)-1; i++ {
			if seqs[i] >= seqs[i+1] {
				t.Errorf("Goroutine %d: out of order at index %d: %d >= %d",
					gid, i, seqs[i], seqs[i+1])
			}
		}
		if len(seqs) != logsPerRoutine {
			t.Errorf("Goroutine %d: missing logs, got %d, want %d",
				gid, len(seqs), logsPerRoutine)
		}
	}

	t.Logf("Order preservation test: all %d goroutines maintained sequence order", len(sequences))
}

func TestConcurrentWorkerPoolLimit(t *testing.T) {
	orig := runCodexTaskFn
	defer func() { runCodexTaskFn = orig }()

	logger, err := NewLoggerWithSuffix("pool-limit")
	if err != nil {
		t.Fatal(err)
	}
	setLogger(logger)
	t.Cleanup(func() {
		_ = closeLogger()
		_ = logger.RemoveLogFile()
	})

	var active int64
	var maxSeen int64
	runCodexTaskFn = func(task TaskSpec, timeout int) TaskResult {
		if task.Context == nil {
			t.Fatalf("context not propagated for task %s", task.ID)
		}
		cur := atomic.AddInt64(&active, 1)
		for {
			prev := atomic.LoadInt64(&maxSeen)
			if cur <= prev || atomic.CompareAndSwapInt64(&maxSeen, prev, cur) {
				break
			}
		}
		select {
		case <-task.Context.Done():
			atomic.AddInt64(&active, -1)
			return TaskResult{TaskID: task.ID, ExitCode: 130, Error: "context cancelled"}
		case <-time.After(30 * time.Millisecond):
		}
		atomic.AddInt64(&active, -1)
		return TaskResult{TaskID: task.ID}
	}

	layers := [][]TaskSpec{{{ID: "t1"}, {ID: "t2"}, {ID: "t3"}, {ID: "t4"}, {ID: "t5"}}}
	results := executeConcurrentWithContext(context.Background(), layers, 5, 2)

	if len(results) != 5 {
		t.Fatalf("unexpected result count: got %d", len(results))
	}
	if maxSeen > 2 {
		t.Fatalf("worker pool exceeded limit: saw %d active workers", maxSeen)
	}

	logger.Flush()
	data, err := os.ReadFile(logger.Path())
	if err != nil {
		t.Fatalf("failed to read log file: %v", err)
	}
	content := string(data)
	if !strings.Contains(content, "worker_limit=2") {
		t.Fatalf("concurrency planning log missing, content: %s", content)
	}
	if !strings.Contains(content, "parallel: start") {
		t.Fatalf("concurrency start logs missing, content: %s", content)
	}
}

func TestConcurrentCancellationPropagation(t *testing.T) {
	orig := runCodexTaskFn
	defer func() { runCodexTaskFn = orig }()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	runCodexTaskFn = func(task TaskSpec, timeout int) TaskResult {
		if task.Context == nil {
			t.Fatalf("context not propagated for task %s", task.ID)
		}
		select {
		case <-task.Context.Done():
			return TaskResult{TaskID: task.ID, ExitCode: 130, Error: "context cancelled"}
		case <-time.After(200 * time.Millisecond):
			return TaskResult{TaskID: task.ID}
		}
	}

	layers := [][]TaskSpec{{{ID: "a"}, {ID: "b"}, {ID: "c"}}}
	go func() {
		time.Sleep(50 * time.Millisecond)
		cancel()
	}()

	results := executeConcurrentWithContext(ctx, layers, 1, 2)
	if len(results) != 3 {
		t.Fatalf("unexpected result count: got %d", len(results))
	}

	cancelled := 0
	for _, res := range results {
		if res.ExitCode != 0 {
			cancelled++
		}
	}

	if cancelled == 0 {
		t.Fatalf("expected cancellation to propagate, got results: %+v", results)
	}
}
