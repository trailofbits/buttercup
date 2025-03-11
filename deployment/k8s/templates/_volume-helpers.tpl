{{/* 
Define reusable volume specifications for our persistent volumes
*/}}

{{- define "buttercup.volumes.scratch" -}}
- name: crs-scratch
  persistentVolumeClaim:
    claimName: {{ .Release.Name }}-crs-scratch
{{- end -}}

{{- define "buttercup.volumes.tasks" -}}
- name: tasks-storage
  persistentVolumeClaim:
    claimName: {{ .Release.Name }}-tasks-storage
{{- end -}}

{{/* 
Define reusable volume mount specifications for our persistent volumes
*/}}

{{- define "buttercup.volumeMounts.scratch" -}}
- name: crs-scratch
  mountPath: {{ include "buttercup.dirs.crs_scratch" . }}
{{- end -}}

{{- define "buttercup.volumeMounts.tasks" -}}
- name: tasks-storage
  mountPath: {{ include "buttercup.dirs.tasks_storage" . }}
{{- end -}}