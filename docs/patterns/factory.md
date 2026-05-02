# Factory

## Problème

Tu dois créer un objet dont le type concret dépend d'un paramètre (config, type, string). L'appelant ne doit pas connaître les classes concrètes.

## Solution

Une fonction ou méthode qui retourne l'objet du bon type selon le paramètre.

## Exemple

```python
# La factory
def create_llm(provider_name: str, temperature: float = 0.2) -> BaseChatModel:
    config = load_provider(provider_name)
    if config["type"] == "anthropic":
        return ChatAnthropic(model=config["model"], temperature=temperature)
    elif config["type"] == "openai":
        return ChatOpenAI(model=config["model"], temperature=temperature)
    elif config["type"] == "ollama":
        return ChatOllama(model=config["model"], temperature=temperature)
    raise ValueError("Provider inconnu: {}".format(provider_name))

# L'appelant ne connaît pas la classe concrète
llm = create_llm("claude-sonnet")
response = llm.invoke(messages)
```

## Quand l'utiliser

- Le type de l'objet est décidé à l'exécution (config, paramètre utilisateur)
- Tu veux découpler la création de l'utilisation
- Ajouter un nouveau type ne doit pas modifier les appelants

## Quand ne PAS l'utiliser

- Tu sais toujours quel type tu crées → instancie directement
- Un seul type existe → pas besoin d'abstraction
