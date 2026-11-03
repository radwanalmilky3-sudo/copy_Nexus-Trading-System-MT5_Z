'use client';
import React, {useEffect,useMemo,useSyncExternalStore} from 'react';
import {brokerAPI} from './api';
import {createBrokerController} from './controller';
import {BrokerSettingsView} from './BrokerSettingsView';

export default function BrokerSettingsTab(){
  const c=useMemo(()=>createBrokerController(brokerAPI),[]);
  const state=useSyncExternalStore(c.subscribe,c.getSnapshot,c.getSnapshot);
  useEffect(()=>{
    void c.load();
    const check=()=>{if(c.checkIdentity())void c.load();};
    const timer=setInterval(check,1000);
    window.addEventListener('storage',check);window.addEventListener('focus',check);
    return ()=>{clearInterval(timer);window.removeEventListener('storage',check);window.removeEventListener('focus',check);c.dispose();};
  },[c]);
  return <BrokerSettingsView controller={c} state={state}/>;
}
