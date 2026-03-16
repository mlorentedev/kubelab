{{/*
Common labels
*/}}
{{- define "kubelab-app.labels" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/component: {{ .component | default "app" }}
app.kubernetes.io/part-of: kubelab
{{- end }}

{{/*
Selector labels
*/}}
{{- define "kubelab-app.selectorLabels" -}}
app.kubernetes.io/name: {{ .name }}
{{- end }}
