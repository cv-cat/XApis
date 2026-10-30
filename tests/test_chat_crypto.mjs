import test from 'node:test';
import assert from 'node:assert/strict';
import {sendPayload,keyPayload,messageView} from '../console/static/chat-protocol.mjs';
import {createChat} from '../frontend/node_modules/@xdevplatform/chat-xdk/index.js';

// No account, PIN, or network is used in these encryption round trips.
globalThis.fetch = async () => { throw new Error('Offline test: network disabled'); };
const builtin = process.getBuiltinModule;
process.getBuiltinModule = name => ['http','https','node:http','node:https'].includes(name) ? {get(){throw new Error('Offline test: network disabled');}} : builtin(name);
async function fixture() {
  const chat = await createChat({getAuthToken:async()=>'',juiceboxModule:{Configuration:class{},Client:class{}}});
  const registered = chat.generateKeypairs();
  chat.setIdentity({userId:'123',signingKeyVersion:'1'});
  const keys = chat.getPublicKeys();
  const signingKeys = [{userId:'123',publicKeyVersion:'1',publicKey:registered.publicKey.signingPublicKey,
    identityPublicKey:registered.publicKey.publicKey,identityPublicKeySignature:registered.publicKey.identityPublicKeySignature}];
  chat.setSigningKeys(signingKeys); chat.setCacheKeys(true); chat.setRejectUnverified(true);
  const prepared = chat.prepareConversationKeyChange({conversationId:'123:123',
    publicKeys:[{userId:'123',keyVersion:'1',publicKey:keys.identity}]});
  return {chat,prepared,signingKeys};
}

test('real SDK signs and encrypts text; web payloads expose no private key or plaintext',async()=>{
  const {chat,prepared,signingKeys} = await fixture();
  try {
    const text = 'Synthetic confidential test 私信';
    const payload = chat.encryptMessage({conversationId:'123:123',text,
      conversationKey:prepared.conversationKey,conversationKeyVersion:prepared.conversationKeyVersion});
    const event = chat.decryptEvent({eventB64:payload.eventB64,
      conversationKeys:{[prepared.conversationKeyVersion]:prepared.conversationKey}, signingKeys});
    assert.equal(event.type,'message'); assert.equal(event.content.text,text); assert.equal(event.verified,true);
    const wire = sendPayload('123:123',payload);
    assert.equal(wire.message_id,payload.messageId);
    assert.equal(wire.encoded_message_create_event,payload.encodedMessageCreateEvent);
    assert.equal(wire.encoded_message_event_signature,payload.encodedMessageEventSignature);
    assert.ok(!JSON.stringify(wire).includes(text));
    const keys = keyPayload(prepared);
    assert.equal(keys.conversation_participant_keys[0].user_id,'123');
    assert.equal(keys.action_signatures[0].message_event_signature.signature,prepared.actionSignatures[0].messageEventSignature.signature);
    assert.ok(!JSON.stringify(keys).includes(Buffer.from(prepared.conversationKey).toString('base64')));
    const tampered = Uint8Array.from(Buffer.from(payload.eventB64,'base64')); tampered[Math.floor(tampered.length/2)] ^= 1;
    assert.throws(()=>chat.decryptEvent({eventB64:Buffer.from(tampered).toString('base64'),conversationKeys:{[prepared.conversationKeyVersion]:prepared.conversationKey},signingKeys}));
  } finally { prepared.conversationKey.fill(0); chat.free(); }
});

test('history cursors compare numeric IDs without losing precision and omit raw keys',()=>{
  const view = messageView({messages:[{event:{type:'keyChange',sequenceId:'9223372036854775805',conversationKeyVersion:'1700000000001'}},
    {event:{type:'message',id:'fixture-id',sequenceId:'9223372036854775804',senderId:'123',content:{text:'fixture'},verified:true}}],
    errors:{},conversationKeys:{keys:{private:'never-return'}}});
  assert.equal(view.before,'9223372036854775804'); assert.equal(view.key_before,'1700000000001');
  assert.equal(view.messages.length,1); assert.ok(!JSON.stringify(view).includes('never-return'));
});


test('a missing historical key event cannot skip messages when computing pagination',()=>{
  const result = messageView({messages:[
    {originalB64:'missing-key',event:{type:'keyChange',sequenceId:'10',conversationKeyVersion:'1'}},
    {originalB64:'page-message',event:{type:'message',sequenceId:'500',content:{text:'fixture'}}}
  ],errors:{}},['page-message']);
  assert.equal(result.before,'500');
});
