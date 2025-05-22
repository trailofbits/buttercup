{{/*
Define constants for directories that are used across multiple services
*/}}
{{- define "buttercup.dirs.crs_scratch" -}}
/crs_scratch
{{- end -}}

{{/*
Define imagePullSecrets for pod specs - using ghcr-auth to match Terraform
*/}}
{{- define "buttercup.imagePullSecrets" -}}
imagePullSecrets:
  - name: ghcr-auth
  - name: docker-auth
{{- end -}}

{{- define "buttercup.dirs.tasks_storage" -}}
/tasks_storage
{{- end -}}

{{/*
Define the Redis init container template that can be included in multiple deployments
*/}}
{{- define "buttercup.waitForRedis" -}}
- name: wait-for-redis
  image: busybox:1.28
  command: ['sh', '-c', 'until nc -z {{ .Release.Name }}-redis-master 6379; do echo waiting for redis; sleep 2; done;']
{{- end -}}

{{/*
Define the LiteLLM health check init container template
*/}}
{{- define "buttercup.waitForLiteLLM" -}}
- name: wait-for-litellm
  image: curlimages/curl:8.6.0
  command: ['sh', '-c', 'until curl --silent -f http://{{ .Release.Name }}-litellm:4000/health/readiness; do echo waiting for litellm; sleep 2; done;']
{{- end -}}

{{/*
Define a health check command that works with signal_alive_health_check() function
It checks if /tmp/health_check_alive file exists and has a recent timestamp
*/}}
{{- define "buttercup.healthCheck" -}}
- sh
- -c
- |
  # Check if health file exists
  if [ ! -f /tmp/health_check_alive ]; then
    echo "Health file not found"
    exit 1
  fi
  
  # Read timestamp from file
  TIMESTAMP=$(cat /tmp/health_check_alive)
  NOW=$(date +%s)
  ELAPSED=$((NOW - TIMESTAMP))
  
  # Maximum allowed time without updates (in seconds)
  MAX_STALE_TIME={{ .maxStaleTime | default 600 }}
  
  # Check if timestamp is too old
  if [ $ELAPSED -gt $MAX_STALE_TIME ]; then
    echo "Health file is stale (last updated $ELAPSED seconds ago, max allowed: $MAX_STALE_TIME)"
    exit 1
  fi
  
  # Health check passed
  exit 0
{{- end -}}

{{/*
Define standard container volumeMounts for bots
*/}}
{{- define "buttercup.standardVolumeMounts" -}}
- name: crs-scratch
  mountPath: {{ include "buttercup.dirs.crs_scratch" . }}
{{- if .usesTasksStorage }}
- name: tasks-storage
  mountPath: {{ include "buttercup.dirs.tasks_storage" . }}
{{- end }}
{{- end -}}

{{/*
Node Local Volume Mount Helper
Conditionally adds the volume mount for node-local storage if enabled globally.
Expects the root context '.' to be passed.
Usage: {{- include "buttercup.nodeLocalVolumeMount" . | nindent 10 }}
*/}}
{{- define "buttercup.nodeLocalVolumeMount" -}}
{{- if .Values.global.volumes.nodeLocal.enabled }}
- name: node-local-storage
  mountPath: {{ .Values.global.volumes.nodeLocal.mountPath }}
{{- end }}
{{- end -}}

{{/*
Node Local Volume Definition Helper
Conditionally adds the volume definition for node-local storage if enabled globally.
Expects the root context '.' to be passed.
Usage: {{- include "buttercup.nodeLocalVolume" . | nindent 8 }}
*/}}
{{- define "buttercup.nodeLocalVolume" -}}
{{- if .Values.global.volumes.nodeLocal.enabled }}
- name: node-local-storage
  hostPath:
    path: {{ .Values.global.volumes.nodeLocal.hostPath }}
    type: {{ .Values.global.volumes.nodeLocal.type }}
{{- end }}
{{- end -}}


{{/*
Node Local CRS Scratch Path Helper
Constructs the path to CRS scratch directory, prepending the node-local mountPath if enabled.
Properly handles path joining to avoid double slashes.
Usage: {{ include "buttercup.nodeLocalCrsScratchPath" . }}
*/}}
{{- define "buttercup.nodeLocalCrsScratchPath" -}}
{{- if .Values.global.volumes.nodeLocal.enabled -}}
{{- printf "%s%s" (trimSuffix "/" .Values.global.volumes.nodeLocal.mountPath) (include "buttercup.dirs.crs_scratch" .) -}}
{{- else -}}
{{- include "buttercup.dirs.crs_scratch" . -}}
{{- end -}}
{{- end -}}

{{/*
Node Local Tasks Storage Path Helper
Constructs the path to tasks storage directory, prepending the node-local mountPath if enabled.
Properly handles path joining to avoid double slashes.
Usage: {{ include "buttercup.nodeLocalTasksStoragePath" . }}
*/}}
{{- define "buttercup.nodeLocalTasksStoragePath" -}}
{{- if .Values.global.volumes.nodeLocal.enabled -}}
{{- printf "%s%s" (trimSuffix "/" .Values.global.volumes.nodeLocal.mountPath) (include "buttercup.dirs.tasks_storage" .) -}}
{{- else -}}
{{- include "buttercup.dirs.tasks_storage" . -}}
{{- end -}}
{{- end -}}

{{/*
Define Docker Host environment variable for Unix socket
*/}}
{{- define "buttercup.env.dockerSocket" }}
- name: DOCKER_HOST
  value: {{ include "buttercup.core.dockerSocketEndpoint" . }}
{{- end }}

{{/*
Define Docker Host environment variable for Unix socket
*/}}
{{- define "buttercup.core.dockerEndpoint" -}}
tcp://localhost:2375
{{- end -}}

{{/*
Include the dind DaemonSet template
*/}}
{{- define "buttercup.templates.dind-daemonset" -}}
{{ include (print $.Template.BasePath "/dind-daemonset.yaml") . }}
{{- end -}}

{{/*
Define Docker Socket volume mount
*/}}
{{- define "buttercup.dockerSocketVolumeMount" -}}
- name: docker-socket-dir
  mountPath: {{ include "buttercup.core.uniqueDockerSocketDir" . }}
{{- end -}}

{{/*
Define Docker Socket volume
*/}}
{{- define "buttercup.dockerSocketVolume" -}}
- name: docker-socket-dir
  hostPath:
    path: {{ include "buttercup.core.uniqueDockerSocketDir" . }}
    type: DirectoryOrCreate
{{- end -}}

{{/*
Define a wait-for-docker init container that checks if the Docker socket is available
*/}}
{{- define "buttercup.waitForDocker" -}}
- name: wait-for-docker
  image: busybox:1.28
  command: ['sh', '-c', 'until [ -S {{ include "buttercup.core.dockerSocketPath" . }} ]; do echo waiting for docker socket; sleep 2; done;']
  volumeMounts:
  {{- include "buttercup.dockerSocketVolumeMount" . | nindent 2 }}
{{- end -}}
