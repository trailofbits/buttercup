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
Define Docker-in-Docker sidecar container
*/}}
{{- define "buttercup.dindSidecar" -}}
- name: dind
  image: "docker:24.0.6-dind"
  securityContext:
    privileged: true
  resources:
    requests:
      cpu: "{{ .Values.dind.resources.requests.cpu | default "250m" }}"
      memory: "{{ .Values.dind.resources.requests.memory | default "512Mi" }}"
    limits:
      cpu: "{{ .Values.dind.resources.limits.cpu | default "500m" }}"
      memory: "{{ .Values.dind.resources.limits.memory | default "1Gi" }}"
  env:
    - name: DOCKER_TLS_CERTDIR
      value: ""
  volumeMounts:
    - name: crs-scratch
      mountPath: {{ include "buttercup.dirs.crs_scratch" . }}
    - name: dind-storage
      mountPath: /var/lib/docker
    {{- include "buttercup.nodeLocalVolumeMount" . | nindent 4 }}
    {{- if .Values.extraVolumeMounts }}
    {{- range .Values.extraVolumeMounts }}
    - name: {{ .name }}
      mountPath: {{ .mountPath }}
    {{- end }}
    {{- end }}
{{- end -}}

{{/*
Define Docker-in-Docker volume
*/}}
{{- define "buttercup.dindVolume" -}}
- name: dind-storage
  emptyDir: {}
{{- end -}}

{{/*
Define Docker Host environment variable for sidecar
*/}}
{{- define "buttercup.dockerHostEnv" -}}
{{- include "buttercup.env.docker" . }}
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
