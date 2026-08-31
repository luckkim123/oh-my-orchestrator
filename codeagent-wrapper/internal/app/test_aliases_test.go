package wrapper

import (
	runtaskset "codeagent-wrapper/internal/application/runtaskset"
	config "codeagent-wrapper/internal/config"
	domaintask "codeagent-wrapper/internal/domain/task"
	executor "codeagent-wrapper/internal/executor"
	backend "codeagent-wrapper/internal/infrastructure/backend"
)

type Config = config.Config
type Backend = backend.Backend
type CodexBackend = backend.CodexBackend
type ClaudeBackend = backend.ClaudeBackend
type AgyBackend = backend.AgyBackend
type ParallelConfig = runtaskset.ParallelConfig
type TaskSpec = executor.TaskSpec
type TaskResult = domaintask.TaskResult
