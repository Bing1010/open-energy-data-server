// App.js
import React, { useState } from 'react';
import './App.css';
import RestTab from './RestTab';
import MetadataTab from './MetadataTab';
import { DBProvider } from './DBContext';

function App() {
  const [activeTab, setActiveTab] = useState('rest');

  return (
    <DBProvider>
      <div className="App">
        <header className="App-header">
          <h1>OEDS Explorer</h1>
          <div style={{ display: 'flex' }}>
            <button className="button" onClick={() => setActiveTab('rest')}>REST</button>
            <button className="button" onClick={() => setActiveTab('metadata')}>Metadata</button>
          </div>
        </header>
        <div className="tab-content">
          {activeTab === 'rest' && <RestTab />}
          {activeTab === 'metadata' && <MetadataTab />}
        </div>
      </div>
    </DBProvider>
  );
}

export default App;
