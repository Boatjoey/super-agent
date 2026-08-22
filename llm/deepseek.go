package llm

// NewDeepSeek returns an OpenAIModel configured for DeepSeek API.
func NewDeepSeek(cfg ProviderConfig) *OpenAIModel {
	cfg = withDefaults(cfg, ProviderConfig{
		BaseURL: "https://api.deepseek.com",
		Model:   "deepseek-reasoner",
	})
	return newOpenAIModel(cfg)
}
