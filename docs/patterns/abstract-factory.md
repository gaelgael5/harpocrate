# Abstract Factory

## Probleme
On doit creer des familles d'objets lies (ex: composants UI par theme, ou providers LLM par type) sans coupler le code appelant aux classes concretes. Changer de famille implique de modifier chaque point d'instanciation.

## Solution
Definir une interface factory qui produit tous les objets d'une famille. Le code appelant utilise la factory sans connaitre les implementations concretes. Changer de famille = changer de factory.

## Exemple
```python
class ChannelFactory(ABC):
    @abstractmethod
    def create_sender(self) -> MessageSender: ...
    @abstractmethod
    def create_receiver(self) -> MessageReceiver: ...

class DiscordFactory(ChannelFactory):
    def create_sender(self) -> MessageSender:
        return DiscordSender(bot_token=os.environ["DISCORD_BOT_TOKEN"])
    def create_receiver(self) -> MessageReceiver:
        return DiscordPoller(bot_token=os.environ["DISCORD_BOT_TOKEN"])

class EmailFactory(ChannelFactory):
    def create_sender(self) -> MessageSender:
        return SmtpSender(host=os.environ["SMTP_HOST"])
    def create_receiver(self) -> MessageReceiver:
        return ImapReceiver(host=os.environ["IMAP_HOST"])

# Usage : le code appelant ne connait pas Discord/Email
factory = DiscordFactory() if channel == "discord" else EmailFactory()
sender = factory.create_sender()
```

## Quand l'utiliser
- Plusieurs familles d'objets interdependants (Discord sender+receiver, Email sender+receiver)
- Le code appelant ne doit pas dependre des classes concretes
- On veut pouvoir switcher de famille a chaud (ex: DEFAULT_CHANNEL)
- Les objets d'une famille doivent etre coherents entre eux

## Quand ne PAS l'utiliser
- Une seule famille existe et n'evoluera pas
- Les objets de la famille n'ont pas de lien logique entre eux
- La complexite de la factory depasse celle du probleme initial
