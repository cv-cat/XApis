// Pure adapters: private keys and plaintext never enter web API payloads.
export function sendPayload(conversationId, payload) {
  return {conversation_id: conversationId, message_id: payload.messageId,
    encoded_message_create_event: payload.encodedMessageCreateEvent,
    encoded_message_event_signature: payload.encodedMessageEventSignature};
}
export function keyPayload(prepared) {
  return {conversation_id: prepared.conversationId,
    conversation_key_version: prepared.conversationKeyVersion,
    conversation_participant_keys: prepared.conversationParticipantKeys.map(k => ({user_id:k.userId,
      public_key_version:k.publicKeyVersion, encrypted_conversation_key:k.encryptedConversationKey})),
    action_signatures: prepared.actionSignatures.map(s => ({message_id:s.messageId,
      encoded_message_event_detail:s.encodedMessageEventDetail,
      message_event_signature:{public_key_version:s.messageEventSignature.publicKeyVersion,
        signature_version:s.messageEventSignature.signatureVersion,signature:s.messageEventSignature.signature,
        signing_public_key:s.messageEventSignature.signingPublicKey}}))};
}
export function messageView(decoded, pageEvents = null) {
  const events = decoded.messages.map(m => m.event);
  const pageSet = pageEvents ? new Set(pageEvents) : null;
  const cursorEvents = pageSet ? decoded.messages.filter(m => pageSet.has(m.originalB64)).map(m => m.event) : events;
  const minimum = values => values.filter(v => /^\d+$/.test(v || "")).reduce((a,b) => !a || BigInt(b)<BigInt(a) ? b : a,null);
  return {messages:events.filter(e => e.type === "message" && e.content?.contentType !== "reaction" && e.content?.contentType !== "reactionRemoved").map(e => ({
    id:e.id || e.sequenceId, sequence:e.sequenceId, sender_id:e.senderId,
    text:e.content?.text || e.content?.newText || "[附件或其他消息类型]",
    created:e.createdAtMsec ? e.createdAtMsec/1000 : null, verified:e.verified,
  })), before:minimum(cursorEvents.map(e => e.sequenceId)), key_before:minimum(events.filter(e => e.type === "keyChange").map(e => e.conversationKeyVersion)),
    failed_count:Object.keys(decoded.errors || {}).length};
}
