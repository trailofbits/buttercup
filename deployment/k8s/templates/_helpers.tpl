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
